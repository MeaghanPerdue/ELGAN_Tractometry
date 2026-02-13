#!/usr/bin/env python3
# original by Christian Haselgrove
# Modified for ELGAN3 by Meaghan Perdue with Copilot
# GE version with TE-based PDT2 renaming + robust scans.tsv rebuild (Feb 2026)
# Must use version with specific TotalReadoutTime as calculated per site!

# Combines:
#  - GE-specific DWI JSON updates and ses-03 bval/bvec copying (from your GE script)
#  - TE-aware PDw/T2w determination, echo-<n> removal, filesystem sweep (from your Siemens model)
#  - Robust scans.tsv rebuild from filesystem (preserve non-filename columns where possible)

### ------------------------------------------------------------------
### HOW-TO 
### ------------------------------------------------------------------
# Dry-run to preview changes
# python post-heudiconv-bids-compliance-fix-GE.py -n /path/to/bids_root

# Use threshold strategy (default) with echo-index fallback
# python post-heudiconv-bids-compliance-fix-GE.py --fallback-echo-index /path/to/bids_root

# Use relative strategy (shortest TE -> PDw, longest TE -> T2w)
# python post-heudiconv-bids-compliance-fix-GE.py --te-strategy relative /path/to/bids_root

import sys
import os
import pathlib
import argparse
import csv
import json
import re
import shutil
from pathlib import Path
from typing import Optional, Dict, Tuple, List
from collections import defaultdict

# ----------------------------
# Settings / constants
# ----------------------------
BACKUP_EXTENSION = 'bak'  # kept for JSON backups in DWI fix

# TE classification thresholds (ms) — from your Siemens model
PDW_MAX_MS = 20.0     # TE < 20 ms -> PDw
T2W_MIN_MS = 90.0     # 90 < TE < 110 ms -> T2w
T2W_MAX_MS = 110.0

# Regex helpers (from model)
PDT2_SUFFIX_STEM_RE = re.compile(r'_(PDw|T2w)$')         # trailing _PDw/_T2w at end of stem
ECHO_ENTITY_RE = re.compile(r'echo-\d+_')                # echo-<n>_ entity within stem

# ----------------------------
# Small utilities
# ----------------------------
def ensure_bidsignore(bids_dir: pathlib.Path):
    """Ensure a .bidsignore exists."""
    bids_dir = pathlib.Path(bids_dir)
    bids_dir.mkdir(parents=True, exist_ok=True)
    bidsignore_path = bids_dir / '.bidsignore'
    if not bidsignore_path.exists():
        try:
            with open(bidsignore_path, 'w') as f:
                f.write("*.bak\n")
        except Exception as e:
            print(f"Failed to create .bidsignore: {e}")
            return
    else:
        # Append *.bak if not present
        try:
            with open(bidsignore_path, 'r') as f:
                lines = [ln.strip() for ln in f.readlines()]
            if "*.bak" not in lines:
                lines.append("*.bak")
                with open(bidsignore_path, 'w') as f:
                    f.write("\n".join(lines) + "\n")
        except Exception as e:
            print(f"Failed to update .bidsignore: {e}")

def arg_bids_dir(arg):
    bids_dir = pathlib.Path(arg)
    if not bids_dir.exists() or not bids_dir.is_dir():
        raise argparse.ArgumentTypeError(f"{bids_dir}: invalid directory")
    return bids_dir

def iter_sessions(bids_dir):
    """
    Iterate (subject, session, session_dir).
    Prefers participants.tsv if present; otherwise falls back to sub-*/ses-* discovery.
    """
    bids_dir = pathlib.Path(bids_dir)
    part_path = bids_dir / "participants.tsv"
    if part_path.exists():
        with open(part_path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            subjects = [row["participant_id"] for row in reader if "participant_id" in row]
        for subject in sorted(subjects):
            subj_dir = bids_dir / subject
            if not subj_dir.exists():
                print(f"WARNING: Missing subject dir: {subj_dir}")
                continue
            for session_dir in sorted([p for p in subj_dir.iterdir() if p.is_dir() and p.name.startswith("ses-")]):
                yield subject, session_dir.name, session_dir
        return
    # Fallback discovery
    for subj_dir in sorted(bids_dir.glob("sub-*")):
        if not subj_dir.is_dir():
            continue
        for session_dir in sorted([p for p in subj_dir.iterdir() if p.is_dir() and p.name.startswith("ses-")]):
            yield subj_dir.name, session_dir.name, session_dir

def load_json(p: Path):
    if not p.exists():
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except Exception as e:
        print(f"WARNING: Failed to read JSON {p}: {e}")
        return None

def write_json(p: Path, data, dry_run=False, backup=True):
    if dry_run:
        print(f"[dry-run] write JSON {p}")
        return
    if backup and p.exists():
        shutil.move(p, p.with_suffix(p.suffix + f".{BACKUP_EXTENSION}"))
    with open(p, "w") as f:
        json.dump(data, f, indent=4)

# ----------------------------
# TE helpers (from model)
# ----------------------------
def read_te_ms(json_path: Path) -> Optional[float]:
    """
    Return EchoTime in milliseconds from a BIDS JSON sidecar.
    - BIDS standard EchoTime is in seconds (<=1.0) -> convert to ms
    - If value looks like ms (>1.0), accept as ms (handles non-compliant exports)
    - Fallback: EchoTimes[0] or EchoTimeDisplay if present
    """
    d = load_json(json_path)
    if not d:
        return None
    te = d.get("EchoTime", None)
    if te is None:
        ets = d.get("EchoTimes", None)
        if isinstance(ets, (list, tuple)) and len(ets) > 0:
            te = ets[0]
    if te is None:
        te = d.get("EchoTimeDisplay", None)
    if te is None:
        return None
    try:
        te = float(te)
    except Exception:
        return None
    if te <= 1.0:
        return te * 1000.0  # seconds -> ms
    return te  # already ms

def modality_from_te(te_ms: Optional[float]) -> Optional[str]:
    """
    Return 'PDw' if TE < 20 ms; 'T2w' if 90 < TE < 110 ms; else None.
    """
    if te_ms is None:
        return None
    if te_ms < PDW_MAX_MS:
        return "PDw"
    if T2W_MIN_MS < te_ms < T2W_MAX_MS:
        return "T2w"
    return None

def parse_file_name(fname: str) -> dict:
    """Lightweight BIDS-ish filename parser."""
    d = {}
    stem = fname.split(".", 1)[0]
    for part in stem.split("_"):
        if "-" in part:
            k, v = part.split("-", 1)
            if k in ["run", "echo", "rec"]:
                try:
                    v = int(v)
                except Exception:
                    pass
            d[k] = v
        else:
            d["suffix"] = part
    return d

def normalized_pdt2_name_with_suffix(basename: str, suffix: str) -> str:
    """
    Remove any 'echo-<n>_' and existing '_PDw'/'_T2w' from stem, append desired suffix.
    Works with .nii.gz or .json.
    """
    if basename.endswith('.json'):
        stem = basename[:-5]
        ext = '.json'
    elif basename.endswith('.nii.gz'):
        stem = basename[:-7]
        ext = '.nii.gz'
    else:
        stem, ext = os.path.splitext(basename)

    stem = ECHO_ENTITY_RE.sub('', stem)          # remove echo-<n>_
    stem = PDT2_SUFFIX_STEM_RE.sub('', stem)     # drop trailing _PDw/_T2w if present
    new_stem = f"{stem}_{suffix}"
    return f"{new_stem}{ext}"

def entity_key_without_echo_and_suffix(fname: str) -> str:
    """
    Grouping key for 'relative' strategy: remove echo entity and suffix to bind the two echoes.
    """
    if fname.endswith('.nii.gz'):
        stem = fname[:-7]
    elif fname.endswith('.nii'):
        stem = fname[:-4]
    else:
        stem = os.path.splitext(fname)[0]
    stem = ECHO_ENTITY_RE.sub('', stem)
    stem = PDT2_SUFFIX_STEM_RE.sub('', stem)
    # drop the final suffix token (after the last underscore) if it doesn't include a dash
    tokens = stem.split("_")
    if tokens and "-" not in tokens[-1]:
        tokens = tokens[:-1]
    return "_".join(tokens)

# ----------------------------
# PDT2 renaming
# ----------------------------
def rename_pdt2_in_session(
    session_dir: Path,
    te_strategy: str = "threshold",       # 'threshold' or 'relative'
    fallback_echo_index: bool = False,
    dry_run: bool = False
) -> Dict[str, str]:
    """
    Rename anat/*acq-PDT2* files to _PDw/_T2w based on EchoTime (JSON).
    Returns mapping old_rel -> new_rel (relative to session root) for scans.tsv reconciliation.
    """
    mapping: Dict[str, str] = {}
    anat_dir = session_dir / "anat"
    if not anat_dir.exists():
        return mapping

    nii_files = sorted(anat_dir.glob("*acq-PDT2*nii*"))
    if te_strategy == "relative":
        # Group by run ignoring echo and suffix
        groups: Dict[str, List[Path]] = defaultdict(list)
        for nii in nii_files:
            groups[entity_key_without_echo_and_suffix(nii.name)].append(nii)

        for key, files in groups.items():
            # Collect TE for each file
            by_te: List[Tuple[float, Path]] = []
            unresolved: List[Path] = []
            for nii in files:
                json_path = nii.parent / (nii.name.replace(".nii.gz", ".json").replace(".nii", ".json"))
                te_ms = read_te_ms(json_path) if json_path.exists() else None
                if te_ms is None:
                    unresolved.append(nii)
                else:
                    by_te.append((te_ms, nii))

            planned: List[Tuple[Path, str]] = []
            if len(by_te) >= 2:
                by_te.sort(key=lambda x: x[0])  # ascending TE
                planned = [(by_te[0][1], "PDw"), (by_te[-1][1], "T2w")]
            elif fallback_echo_index:
                # fallback using echo index
                for nii in files:
                    info = parse_file_name(nii.name)
                    echo = info.get("echo", None)
                    if echo == 1:
                        planned.append((nii, "PDw"))
                    elif echo == 2:
                        planned.append((nii, "T2w"))

            # Apply renames
            for nii, suffix in planned:
                old_name = nii.name
                new_name = normalized_pdt2_name_with_suffix(old_name, suffix)
                if new_name == old_name:
                    continue
                old_json = nii.parent / old_name.replace(".nii.gz", ".json").replace(".nii", ".json")
                new_json = nii.parent / new_name.replace(".nii.gz", ".json").replace(".nii", ".json")
                print(f"  PDT2 rename (relative): {old_name} -> {new_name}")
                if not dry_run:
                    if nii.exists():
                        nii.rename(nii.parent / new_name)
                    else:
                        print(f"    WARNING: missing NIfTI: {nii}")
                    if old_json.exists():
                        old_json.rename(new_json)
                    else:
                        print(f"    WARNING: missing JSON: {old_json}")
                old_rel = str(Path("anat") / old_name)
                new_rel = str(Path("anat") / new_name)
                mapping[old_rel] = new_rel

    else:
        # 'threshold' strategy — classify each file by TE independently
        for nii in nii_files:
            base = nii.name
            json_path = nii.parent / base.replace(".nii.gz", ".json").replace(".nii", ".json")
            te_ms = read_te_ms(json_path) if json_path.exists() else None
            suffix = modality_from_te(te_ms)
            if suffix is None and fallback_echo_index:
                m = re.search(r'echo-(\d+)_', base)
                if m:
                    try:
                        echo = int(m.group(1))
                        suffix = "PDw" if echo == 1 else "T2w"
                    except Exception:
                        pass
            if suffix is None:
                print(f"  WARNING: Cannot determine PDw/T2w for {base} (no usable TE/echo). Skipping.")
                continue

            new_name = normalized_pdt2_name_with_suffix(base, suffix)
            if new_name == base:
                continue
            new_path = nii.parent / new_name
            old_json = nii.parent / base.replace(".nii.gz", ".json").replace(".nii", ".json")
            new_json = nii.parent / new_name.replace(".nii.gz", ".json").replace(".nii", ".json")
            print(f"  PDT2 rename (threshold): {base} -> {new_name}")
            if not dry_run:
                if nii.exists():
                    nii.rename(new_path)
                else:
                    print(f"    WARNING: Missing NIfTI, cannot rename: {nii}")
                if old_json.exists():
                    old_json.rename(new_json)
                else:
                    print(f"    WARNING: Missing JSON, cannot rename: {old_json}")
            old_rel = str(Path("anat") / base)
            new_rel = str(Path("anat") / new_name)
            mapping[old_rel] = new_rel

    return mapping

# ----------------------------
# Robust scans.tsv rebuild
# ----------------------------
def rebuild_scans_tsv(session_dir: Path, mapping_old_to_new: Dict[str, str], dry_run=False):
    """
    Rebuild session scans.tsv from the actual files on disk.
    - Preserve any non-filename columns from the old TSV where we can map the row
      (either same filename or via old->new mapping after renames).
    - Drop rows for files that do not exist anymore.
    - Add rows for new files.
    """
    subj = session_dir.parent.name
    ses = session_dir.name
    scans_tsv = session_dir / f"{subj}_{ses}_scans.tsv"

    # Current on-disk files (relative paths)
    current_files: List[str] = []
    for subdir in ["anat", "dwi", "func", "fmap", "perf", "pet", "meg", "eeg"]:
        d = session_dir / subdir
        if d.exists():
            for nii in sorted(d.rglob("*.nii*")):
                current_files.append(str(nii.relative_to(session_dir)))

    # Load existing
    existing_rows: List[dict] = []
    existing_cols: List[str] = []
    if scans_tsv.exists():
        with open(scans_tsv) as f:
            reader = csv.DictReader(f, delimiter="\t")
            existing_cols = reader.fieldnames or []
            for row in reader:
                existing_rows.append(row)

    by_filename = {r.get("filename", ""): r for r in existing_rows if r.get("filename")}

    # Build new rows
    inv_map = {v: k for k, v in mapping_old_to_new.items()}
    new_rows: List[dict] = []
    for rel in current_files:
        if rel in by_filename:
            row = dict(by_filename[rel])
        else:
            former = inv_map.get(rel)
            if former and former in by_filename:
                row = dict(by_filename[former])
            else:
                row = {}
            row["filename"] = rel
        new_rows.append(row)

    new_rows.sort(key=lambda r: r.get("filename", ""))

    other_cols = [c for c in existing_cols if c and c != "filename"]
    fieldnames = ["filename"] + other_cols if other_cols else ["filename"]

    if dry_run:
        print(f"[dry-run] Would write {scans_tsv} with {len(new_rows)} rows")
        return

    with open(scans_tsv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in new_rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    print(f"Rebuilt: {scans_tsv} ({len(new_rows)} rows)")

# ----------------------------
# GE-specific DWI JSON fix (from your GE script)
# ----------------------------
def fix_dwi_json(session_dir: Path, dry_run=False):
    """Apply GE DWI JSON field updates."""
    dwi_dir = session_dir / "dwi"
    if not dwi_dir.exists():
        return
    for json_file in sorted(dwi_dir.glob("*.json")):
        data = load_json(json_file)
        if data is None:
            continue
        changed = False
        if data.get("PhaseEncodingAxis") != "j":
            data["PhaseEncodingAxis"] = "j"; changed = True
        if data.get("PhaseEncodingDirection") != "j-":
            data["PhaseEncodingDirection"] = "j-"; changed = True
        if data.get("TotalReadoutTime") != 0.09274301886792452:
            data["TotalReadoutTime"] = 0.09274301886792452; changed = True
        if changed:
            print(f"  Updating DWI JSON fields: {json_file.name}")
            write_json(json_file, data, dry_run=dry_run, backup=True)

# ----------------------------
# Master bval/bvec copy (ses-03)
# ----------------------------
def copy_master_bvals(bids_dir: Path, session_dir: Path, session: str, dry_run=False):
    master_bval = bids_dir / 'dwi.bval'
    master_bvec = bids_dir / 'dwi.bvec'
    if not master_bval.exists() or not master_bvec.exists():
        print(f"ERROR: Missing master dwi.bval or dwi.bvec in {bids_dir}")
        return
    if session != "ses-03":
        return
    dwi_dir = session_dir / "dwi"
    if not dwi_dir.exists():
        print(f"WARNING: No dwi dir: {dwi_dir}")
        return
    for nii_file in sorted(dwi_dir.glob("*.nii*")):
        base = nii_file.name.replace(".nii.gz", "").replace(".nii", "")
        bval_out = dwi_dir / f"{base}.bval"
        bvec_out = dwi_dir / f"{base}.bvec"
        if dry_run:
            print(f"[dry-run] Would copy {master_bval} -> {bval_out}")
            print(f"[dry-run] Would copy {master_bvec} -> {bvec_out}")
        else:
            shutil.copy2(master_bval, bval_out)
            shutil.copy2(master_bvec, bvec_out)
            print(f"Copied {master_bval} -> {bval_out}")
            print(f"Copied {master_bvec} -> {bvec_out}")

# ----------------------------
# Main
# ----------------------------
def main():
    parser = argparse.ArgumentParser(
        description="GE post-heudiconv: TE-based PDT2 renaming + robust scans.tsv + GE DWI JSON fixes",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run", "-n", action="store_true", help="Preview changes without writing.")
    parser.add_argument("--fallback-echo-index", action="store_true",
                        help="If EchoTime missing, fall back to echo-<n> for PDT2 renaming.")
    parser.add_argument("--te-strategy", choices=["threshold", "relative"], default="threshold",
                        help="Use fixed TE thresholds (default) or per-run relative (shorter->PDw, longer->T2w).")
    parser.add_argument("bids_dir", type=arg_bids_dir)

    args = parser.parse_args()
    bids_dir = pathlib.Path(args.bids_dir)
    ensure_bidsignore(bids_dir)

    # Pass 1: DWI JSON fixes (GE fields)
    for subject, session, session_dir in iter_sessions(bids_dir):
        print(subject, session)
        fix_dwi_json(session_dir, dry_run=args.dry_run)

    # Pass 2: PDT2 renaming by EchoTime (filesystem sweep in anat/)
    # Collect mappings per session for scans.tsv reconciliation
    session_mappings: Dict[Tuple[str, str], Dict[str, str]] = {}
    for subject, session, session_dir in iter_sessions(bids_dir):
        print(subject, session)
        mapping = rename_pdt2_in_session(
            session_dir,
            te_strategy=args.te_strategy,
            fallback_echo_index=args.fallback_echo_index,
            dry_run=args.dry_run
        )
        session_mappings[(subject, session)] = mapping

    # Pass 3: Rebuild scans.tsv from filesystem (preserve non-filename columns where possible)
    for subject, session, session_dir in iter_sessions(bids_dir):
        mapping = session_mappings.get((subject, session), {})
        rebuild_scans_tsv(session_dir, mapping, dry_run=args.dry_run)

    # Pass 4: Copy master bval/bvec for ses-03
    for subject, session, session_dir in iter_sessions(bids_dir):
        copy_master_bvals(bids_dir, session_dir, session, dry_run=args.dry_run)

    sys.exit(0)

if __name__ == "__main__":
    main()
