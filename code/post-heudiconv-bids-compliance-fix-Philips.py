#!/usr/bin/env python3
# original by Christian Haselgrove
# Modified for ELGAN3 by Meaghan Perdue with copilot
# Philips version with TE-based PDT2 renaming + robust scans.tsv rebuild + safe fmap/DWI JSON updates (Feb 2026)

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
BACKUP_EXTENSION = 'bak'   # JSON backup suffix when we change JSONs

# Threshold-based TE classification (ms)
PDW_MAX_MS = 20.0          # TE < 20 ms -> PDw
T2W_MIN_MS = 90.0          # 90 < TE < 110 ms -> T2w
T2W_MAX_MS = 110.0

# Default Philips DWI PhaseEncodingDirection if missing
# Adjust here if your site encodes differently.
PHILIPS_DEFAULT_DWI_PEDIR = "j-"

# Regex helpers
PDT2_SUFFIX_STEM_RE = re.compile(r'_(PDw|T2w)$')   # trailing _PDw/_T2w at end of stem
ECHO_ENTITY_RE = re.compile(r'echo-\d+_')          # echo-<n>_ entity within stem

# ----------------------------
# Utilities
# ----------------------------
def ensure_bidsignore(bids_dir: pathlib.Path):
    """Ensure a .bidsignore exists and includes *.bak."""
    bids_dir = pathlib.Path(bids_dir)
    bids_dir.mkdir(parents=True, exist_ok=True)
    bidsignore_path = bids_dir / '.bidsignore'
    if not bidsignore_path.exists():
        with open(bidsignore_path, 'w') as f:
            f.write("*.bak\n")
    else:
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
    Prefer participants.tsv if present; otherwise fall back to sub-*/ses-* discovery.
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

# ----------------------------
# TE helpers (threshold-based)
# ----------------------------
def read_te_ms(json_path: Path) -> Optional[float]:
    """
    Return EchoTime in milliseconds.
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

def modality_from_te_threshold(te_ms: Optional[float]) -> Optional[str]:
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

def normalized_pdt2_name_with_suffix(basename: str, suffix: str) -> str:
    """
    Remove any 'echo-<n>_' and existing '_PDw'/'_T2w' from stem, then append suffix.
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

# ----------------------------
# PDT2 renaming (threshold TE)
# ----------------------------
def rename_pdt2_in_session_threshold(
    session_dir: Path,
    fallback_echo_index: bool = False,
    dry_run: bool = False
) -> Dict[str, str]:
    """
    Rename anat/*acq-PDT2* files to _PDw/_T2w based on EchoTime thresholds.
    Returns mapping old_rel -> new_rel (session-relative) for scans.tsv reconciliation.
    """
    mapping: Dict[str, str] = {}
    anat_dir = session_dir / "anat"
    if not anat_dir.exists():
        return mapping

    for nii in sorted(anat_dir.glob("*acq-PDT2*nii*")):
        base = nii.name
        json_path = nii.parent / base.replace(".nii.gz", ".json").replace(".nii", ".json")
        te_ms = read_te_ms(json_path) if json_path.exists() else None
        suffix = modality_from_te_threshold(te_ms)

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
        print(f"  PDT2 rename: {base} -> {new_name}")
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
# scans.tsv rebuild (robust)
# ----------------------------
def rebuild_scans_tsv(session_dir: Path, mapping_old_to_new: Dict[str, str], dry_run=False):
    """
    Rebuild session scans.tsv from actual files on disk.
    - Preserve non-filename columns from old TSV where resolvable (same name or via mapping)
    - Drop rows for missing files
    - Add rows for new files
    """
    subj = session_dir.parent.name
    ses = session_dir.name
    scans_tsv = session_dir / f"{subj}_{ses}_scans.tsv"

    # Current files on disk (relative paths)
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

    inv_map = {v: k for k, v in mapping_old_to_new.items()}

    # Build new rows
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
# fmap updates (Philips-safe)
# ----------------------------
def gather_abcd_targets(session_dir: Path) -> List[str]:
    """Return session-relative paths of ABCD1/ABCD2 DWIs to populate IntendedFor."""
    dwi_dir = session_dir / "dwi"
    targets = []
    if dwi_dir.exists():
        for nii in sorted(dwi_dir.glob("*acq-ABCD[12]*.nii*")):
            targets.append(str(nii.relative_to(session_dir)))
    return targets

def update_philips_fmaps(session_dir: Path, dry_run=False, force=False):
    """
    Update fmap JSONs only if fmap/ exists.
      - Set PhaseEncodingDirection from filename dir-AP/PA (if missing)
      - Set TotalReadoutTime from EstimatedTotalReadoutTime (if present)
      - Set IntendedFor and B0FieldIdentifier ONLY if ABCD1/2 targets exist
    """
    fmap_dir = session_dir / "fmap"
    if not fmap_dir.exists():
        return

    targets = gather_abcd_targets(session_dir)  # might be empty
    for j in sorted(fmap_dir.glob("*.json")):
        data = load_json(j)
        if data is None:
            continue
        changed = False

        # PhaseEncodingDirection from name if missing
        name = j.name
        if "PhaseEncodingDirection" not in data:
            if "_dir-AP_" in name:
                data["PhaseEncodingDirection"] = "j-"  # AP -> j-
                changed = True
            elif "_dir-PA_" in name:
                data["PhaseEncodingDirection"] = "j"   # PA -> j
                changed = True

        # TotalReadoutTime <- EstimatedTotalReadoutTime if available and not already set or forced
        if "EstimatedTotalReadoutTime" in data:
            if force or ("TotalReadoutTime" not in data):
                data["TotalReadoutTime"] = data["EstimatedTotalReadoutTime"]
                changed = True

        # IntendedFor + B0FieldIdentifier only if ABCD targets exist
        if targets:
            if force or ("IntendedFor" not in data):
                data["IntendedFor"] = targets
                changed = True
            if force or ("B0FieldIdentifier" not in data):
                data["B0FieldIdentifier"] = "pepolar_ABCD"
                changed = True
        else:
            # Do not set them; keep fmap generic
            pass

        if changed and not dry_run:
            write_json(j, data, dry_run=False, backup=True)
            print(f"  Updated fmap: {j.name}")

# ----------------------------
# DWI JSON updates (applies to ALL DWI scans, including 'plain' ones)
# ----------------------------
def update_philips_dwi_jsons(session_dir: Path, dry_run=False, force=False):
    """
    For every dwi/*.json:
      - Set PhaseEncodingDirection to PHILIPS_DEFAULT_DWI_PEDIR (if missing or forced)
      - Set TotalReadoutTime from EstimatedTotalReadoutTime (if present; if forced or missing)
    No fieldmaps required for this to run.
    """
    dwi_dir = session_dir / "dwi"
    if not dwi_dir.exists():
        return

    for j in sorted(dwi_dir.glob("*.json")):
        data = load_json(j)
        if data is None:
            continue
        changed = False

        if force or ("PhaseEncodingDirection" not in data):
            data["PhaseEncodingDirection"] = PHILIPS_DEFAULT_DWI_PEDIR
            changed = True

        if "EstimatedTotalReadoutTime" in data:
            if force or ("TotalReadoutTime" not in data):
                data["TotalReadoutTime"] = data["EstimatedTotalReadoutTime"]
                changed = True

        if changed and not dry_run:
            write_json(j, data, dry_run=False, backup=True)
            print(f"  Updated DWI JSON: {j.name}")

# ----------------------------
# Main
# ----------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Philips post-heudiconv: TE-based PDT2 renaming + robust scans.tsv + Philips DWI/fmap JSON fixes",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run", "-n", action="store_true", help="Preview changes without writing.")
    parser.add_argument("--fallback-echo-index", action="store_true",
                        help="If EchoTime missing, fall back to echo-<n> for PDT2 renaming.")
    parser.add_argument("--force-json-overwrite", action="store_true",
                        help="Force overwrite JSON fields even if present.")
    parser.add_argument("bids_dir", type=arg_bids_dir)

    args = parser.parse_args()
    bids_dir = pathlib.Path(args.bids_dir)
    ensure_bidsignore(bids_dir)

    # Pass 1: PDT2 renaming by TE thresholds (filesystem sweep)
    session_mappings: Dict[Tuple[str, str], Dict[str, str]] = {}
    for subject, session, session_dir in iter_sessions(bids_dir):
        print(subject, session)
        mapping = rename_pdt2_in_session_threshold(
            session_dir,
            fallback_echo_index=args.fallback_echo_index,
            dry_run=args.dry_run
        )
        session_mappings[(subject, session)] = mapping

    # Pass 2: Update DWI JSONs for ALL DWI scans (plain and ABCD)
    for subject, session, session_dir in iter_sessions(bids_dir):
        print(subject, session)
        update_philips_dwi_jsons(session_dir, dry_run=args.dry_run, force=args.force_json_overwrite)

    # Pass 3: Update fmap JSONs (only if fmap/ exists)
    for subject, session, session_dir in iter_sessions(bids_dir):
        print(subject, session)
        update_philips_fmaps(session_dir, dry_run=args.dry_run, force=args.force_json_overwrite)

    # Pass 4: Rebuild scans.tsv from filesystem (preserve non-filename columns where possible)
    for subject, session, session_dir in iter_sessions(bids_dir):
        mapping = session_mappings.get((subject, session), {})
        rebuild_scans_tsv(session_dir, mapping, dry_run=args.dry_run)

    sys.exit(0)

if __name__ == "__main__":
    main()