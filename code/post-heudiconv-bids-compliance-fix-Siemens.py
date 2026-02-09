#!/usr/bin/env python3
# original by Christian Haselgrove
# Modified for ELGAN3 by Meaghan Perdue (PDT2 handling + TE-aware renaming)
# This version derives PDw/T2w from EchoTime in JSON; falls back to echo number.

import sys
import os
import pathlib
import argparse
import csv
import json
import re
from pathlib import Path

# ----------------------------
# Settings / constants
# ----------------------------
BACKUP_EXTENSION = 'bak'  # Reserved; no backups are created by this script

# TE classification thresholds (ms)
PDW_MAX_MS = 20.0             # TE < 20 ms -> PDw
T2W_MIN_MS = 90.0             # 90 < TE < 110 ms -> T2w
T2W_MAX_MS = 110.0

# Regex helpers
PDT2_SUFFIX_STEM_RE = re.compile(r'_(PDw|T2w)$')  # trailing _PDw/_T2w at end of stem
ECHO_ENTITY_RE = re.compile(r'echo-\d+_')         # echo-<n>_ entity within stem

# ----------------------------
# Small utilities
# ----------------------------
def ensure_bidsignore(bids_dir: pathlib.Path):
    """
    Ensure a .bidsignore exists. If present and doesn't list *.bak, append it.
    (We don't create .bak files here, but keeping this for parity with prior script.)
    """
    bids_dir = pathlib.Path(bids_dir)
    bidsignore_path = bids_dir / '.bidsignore'
    if not bids_dir.exists():
        print(f"Creating missing BIDS directory: {bids_dir}")
        bids_dir.mkdir(parents=True, exist_ok=True)

    if not bidsignore_path.exists():
        try:
            with open(bidsignore_path, 'w') as f:
                f.write("*.bak\n")
        except Exception as e:
            print(f"Failed to create .bidsignore: {e}")
        return

    # Append *.bak if not already present
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
    """argparse argument type for a BIDS directory."""
    bids_dir = pathlib.Path(arg)
    if not bids_dir.exists():
        raise argparse.ArgumentTypeError(f'{bids_dir}: does not exist')
    if not bids_dir.is_dir():
        raise argparse.ArgumentTypeError(f'{bids_dir}: not a directory')
    return bids_dir

def iter_sessions(bids_dir):
    """
    Iterate (subject_id, session_id, session_dir, Scans) for all listed participants/sessions.
    Uses participants.tsv for the subject list; scans are preloaded from each session's scans.tsv.
    """
    part_path = bids_dir / "participants.tsv"
    if not part_path.exists():
        print("ERROR: Missing participants.tsv")
        return
    with open(part_path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        subjects = [row["participant_id"] for row in reader]
    for subject in subjects:
        subj_dir = bids_dir / subject
        if not subj_dir.exists():
            print(f"WARNING: Missing subject directory: {subj_dir}")
            continue
        for session_dir in sorted([p for p in subj_dir.iterdir() if p.is_dir()]):
            scans = Scans(subject, session_dir.name, session_dir)
            yield subject, session_dir.name, session_dir, scans

def parse_file_name(fname):
    """
    Parse BIDS-like filename parts (very lightweight):
      - Maps entities with '-' to dict entries (e.g., acq, run, echo)
      - 'type' is the last underscore segment without a dash (e.g., PDw or T2w)
    """
    d = {}
    for part in fname.split(".", 1)[0].split("_"):
        if "-" in part:
            k, v = part.split("-", 1)
            if k in ["run", "echo"]:
                try:
                    v = int(v)
                except Exception:
                    pass
            d[k] = v
        else:
            d["type"] = part
    return d

# ----------------------------
# Data model
# ----------------------------
class Scans:
    """
    A collection of scans loaded from <sub>/<ses>/<sub>_<ses>_scans.tsv.
    Indexable by filename; iteration yields Scan objects.
    Missing NIfTI rows are tolerated (warn + skip).
    """
    def __init__(self, subject, session, session_dir: Path):
        self._scans = {}
        tsv_path = session_dir / f"{subject}_{session}_scans.tsv"
        if not tsv_path.exists():
            print(f"WARNING: Missing scans.tsv: {tsv_path}")
            return
        with open(tsv_path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                fname = row.get("filename")
                if not fname:
                    print(f"WARNING: Missing filename in {tsv_path}, skipping row.")
                    continue
                try:
                    scan = Scan(session_dir, pathlib.Path(fname))
                    self._scans[fname] = scan
                except Exception as e:
                    print(f"WARNING: Could not load scan {fname}: {e}")

    def __iter__(self):
        return iter(self._scans[k] for k in sorted(self._scans))

    def iter_subdir(self, subdir):
        return (scan for scan in self if scan['subdir'] == subdir)

class Scan:
    """
    Represents one scan + JSON with missing-file tolerance reported upstream.
    """
    def __init__(self, session_dir: Path, relative_path: Path):
        self.path = session_dir / relative_path
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        self.session_path = session_dir.name / relative_path
        base = self.path.name[:-7]  # drop .nii.gz
        self._params = parse_file_name(self.path.name)
        self._params["subdir"] = self.path.parent.name
        self.json_path = self.path.parent / f"{base}.json"
        self.data = None
        if self.json_path.exists():
            try:
                with open(self.json_path) as f:
                    self.data = json.load(f)
            except Exception:
                pass

    def __getitem__(self, key):
        return self._params[key]

    def __repr__(self):
        return f"Scan('{self.path}')"

# ----------------------------
# PDT2 helpers (TE-aware)
# ----------------------------
def read_te_ms(json_path: Path) -> float | None:
    """
    Return EchoTime in milliseconds from a BIDS JSON sidecar.
    - BIDS standard is seconds (<= 1.0) -> convert to ms
    - If value looks like ms (> 1.0), accept as ms (handles non-compliant exports)
    - Falls back to EchoTimes[0] or EchoTimeDisplay when present
    """
    try:
        with open(json_path) as f:
            d = json.load(f)
    except Exception:
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
        return te * 1000.0   # seconds -> ms
    return te               # already looks like ms

def modality_from_te(te_ms: float | None) -> str | None:
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
    Suffix-agnostic normalization for a single basename (either .nii.gz or .json):
      - remove any 'echo-<n>_' entity
      - strip a trailing '_PDw' or '_T2w' from the stem (if present)
      - append the desired suffix
    """
    if basename.endswith('.json'):
        stem = basename[:-5]
        ext = '.json'
    elif basename.endswith('.nii.gz'):
        stem = basename[:-7]
        ext = '.nii.gz'
    else:
        # Unknown extension; treat as plain stem (rare in BIDS)
        stem, ext = os.path.splitext(basename)

    # Remove echo entity anywhere in stem & drop trailing modality suffix if present
    stem = ECHO_ENTITY_RE.sub('', stem)
    stem = PDT2_SUFFIX_STEM_RE.sub('', stem)

    new_stem = f"{stem}_{suffix}"
    return f"{new_stem}{ext}"

# ----------------------------
# scans.tsv updater (TE-aware)
# ----------------------------
def update_scans_tsv(bids_dir: Path, dry_run: bool = False):
    bids_dir = pathlib.Path(bids_dir)
    for subject_dir in bids_dir.glob("sub-*"):
        for session_dir in subject_dir.glob("ses-*"):
            scans_tsv = session_dir / f"{subject_dir.name}_{session_dir.name}_scans.tsv"
            if not scans_tsv.exists():
                print(f"WARNING: Missing scans.tsv: {scans_tsv}")
                continue

            with open(scans_tsv) as f:
                reader = csv.DictReader(f, delimiter="\t")
                rows = list(reader)
                fieldnames = reader.fieldnames

            changed = False
            for row in rows:
                fname = row.get("filename")
                if not fname:
                    print(f"WARNING: Missing filename in {scans_tsv}, skipping row")
                    continue

                # Process only anat PDT2 entries
                if (
                    "anat/" in fname
                    and "acq-PDT2" in fname
                    and (fname.endswith(".nii.gz") or fname.endswith(".json"))
                ):
                    rel_path = Path(fname)
                    abs_path = session_dir / rel_path

                    # Figure out JSON path for this row
                    if fname.endswith(".nii.gz"):
                        json_path = abs_path.with_suffix("").with_suffix(".json")
                    else:
                        json_path = abs_path

                    # TE-based suffix
                    te_ms = read_te_ms(json_path) if json_path.exists() else None
                    suffix = modality_from_te(te_ms)

                    # Fallback to echo number visible in filename
                    if suffix is None:
                        m = re.search(r'echo-(\d+)_', fname)
                        if m:
                            try:
                                echo = int(m.group(1))
                                suffix = "PDw" if echo == 1 else "T2w"
                            except Exception:
                                pass

                    if suffix is None:
                        print(f"WARNING: Cannot determine modality from TE/echo for: {fname}")
                        continue

                    dirname, base = os.path.split(fname)
                    new_base = normalized_pdt2_name_with_suffix(base, suffix)
                    new_fname = os.path.join(dirname, new_base)

                    if new_fname != fname:
                        row["filename"] = new_fname
                        changed = True

            if changed:
                if dry_run:
                    print(f"[DRY-RUN] Would update: {scans_tsv}")
                else:
                    with open(scans_tsv, "w", newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
                        writer.writeheader()
                        writer.writerows(rows)
                    print(f"Updated: {scans_tsv}")

# ----------------------------
# Main
# ----------------------------
def main():
    progname = os.path.basename(sys.argv[0])
    description = 'Normalize ELGAN3 Siemens PDT2 filenames using EchoTime (TE) and update scans.tsv.'
    epilog = f"""
    Behavior:
      - For anat/*acq-PDT2* files, derive PDw/T2w from JSON EchoTime:
          TE < {PDW_MAX_MS:g} ms -> PDw
          {T2W_MIN_MS:g} < TE < {T2W_MAX_MS:g} ms -> T2w
        Fallback: echo-1 -> PDw, echo-2 -> T2w
      - Remove echo-<n>_ from basenames.
      - Rename both .nii.gz and .json sidecars.
      - Update each session's scans.tsv to match.

    Use -n/--dry-run to preview changes without writing.
    """
    parser = argparse.ArgumentParser(description=description, epilog=epilog,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", "-c", action="store_true",
                        help="(Reserved) No-op; kept for compatibility.")
    parser.add_argument("--diff", "-d", action="store_true",
                        help="(Reserved) No-op; kept for compatibility.")
    parser.add_argument("--restore", "-r", action="store_true",
                        help="(Reserved) No-op; kept for compatibility.")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Preview changes without writing.")
    parser.add_argument("bids_dir", type=arg_bids_dir)
    args = parser.parse_args()

    # Ensure .bidsignore exists (harmless even though we don't write .bak)
    ensure_bidsignore(args.bids_dir)

    # --- STEP 1: Rename files on disk (TE-aware) ---
    for subject, session, session_dir, scans in iter_sessions(args.bids_dir):
        print(subject, session)
        for scan in scans.iter_subdir("anat"):
            if scan._params.get("acq") != "PDT2":
                continue

            # Prefer TE from JSON; fallback to echo number if needed
            te_ms = read_te_ms(scan.json_path) if scan.json_path.exists() else None
            suffix = modality_from_te(te_ms)

            if suffix is None and "echo" in scan._params:
                try:
                    echo = int(scan._params["echo"])
                    suffix = "PDw" if echo == 1 else "T2w"
                except Exception:
                    pass

            if suffix is None:
                print(f"  WARNING: Cannot determine PDw/T2w for {scan.path.name} (no usable TE/echo). Skipping.")
                continue

            old_name = scan.path.name
            new_name = normalized_pdt2_name_with_suffix(old_name, suffix)

            if new_name != old_name:
                new_path = scan.path.parent / new_name
                old_json = scan.json_path
                new_json = Path(str(new_path).replace(".nii.gz", ".json"))

                print(f"  Renaming {old_name} → {new_name}")
                if not args.dry_run:
                    # Rename NIfTI
                    if scan.path.exists():
                        scan.path.rename(new_path)
                    else:
                        print(f"WARNING: Missing NIfTI, cannot rename: {scan.path}")

                    # Rename JSON
                    if old_json.exists():
                        old_json.rename(new_json)
                    else:
                        print(f"WARNING: Missing JSON, cannot rename: {old_json}")
            else:
                # Already normalized
                pass

    # --- STEP 2: Update scans.tsv to reflect final names ---
    update_scans_tsv(args.bids_dir, dry_run=args.dry_run)

if __name__ == "__main__":
    main()

#### eof ####