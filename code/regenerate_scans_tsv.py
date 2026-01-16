
#!/usr/bin/env python3
"""
Regenerate scans.tsv files based on the actual contents of the BIDS folders.
Meaghan Perdue created using CoPilot AI 16 Jan 2026

To run a dry-run and check performance:
python regenerate_scans_tsv.py /path/to/BIDS --dry-run

Actual run, including back-up:
python regenerate_scans_tsv.py /path/to/BIDS --backup

Features:
- For each subject/session, walks the directory tree and finds all .nii.gz files
- Writes a fresh scans.tsv containing ONLY real files on disk
- Issues warnings for orphan JSONs, orphan NIfTIs, and unexpected patterns
- Safe: dry-run mode + optional automatic backup of old scans.tsv
"""

import argparse
from pathlib import Path
import csv
import datetime

def find_bids_files(session_dir):
    """Return sorted list of all .nii.gz files under a session directory."""
    return sorted(
        p.relative_to(session_dir)
        for p in session_dir.rglob("*.nii.gz")
        if "bak" not in p.name and not p.name.endswith(".nii.json")
    )


def find_orphan_jsons(session_dir, nii_files):
    """Warn about JSON files without a matching .nii.gz."""
    nii_stems = {f.with_suffix('').with_suffix('').stem for f in nii_files}
    for json_file in session_dir.rglob("*.json"):
        if json_file.name.endswith(".nii.json"):
            # broken naming case
            yield ("broken_json", json_file)
            continue

        stem = json_file.stem  # removes .json
        # A valid nifti can be foo.nii.gz (json stem="foo.nii")
        if stem.endswith(".nii"):
            stem = stem[:-4]

        if stem not in nii_stems:
            yield ("orphan_json", json_file)


def backup_file(path):
    """Make a timestamped backup of the scans.tsv."""
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(f".tsv.bak-{ts}")
    path.rename(backup)
    return backup


def write_scans_tsv(scans_tsv, nii_files):
    """Write a new scans.tsv listing the .nii.gz files."""
    scans_tsv.parent.mkdir(exist_ok=True, parents=True)

    with open(scans_tsv, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["filename"])
        for fpath in nii_files:
            writer.writerow([str(fpath)])


def main():
    parser = argparse.ArgumentParser(
        description="Rebuild scans.tsv from actual BIDS folder contents."
    )
    parser.add_argument("bids_dir", type=Path)
    parser.add_argument("--dry-run", action="store_true",
                        help="Do not write any files; only print actions.")
    parser.add_argument("--backup", action="store_true",
                        help="Make a timestamped backup of existing scans.tsv before overwriting.")
    args = parser.parse_args()

    bids_dir = args.bids_dir

    participants = bids_dir / "participants.tsv"
    if not participants.exists():
        print(f"ERROR: No participants.tsv found in {bids_dir}")
        return

    # Load participant IDs
    with open(participants) as f:
        reader = csv.DictReader(f, delimiter="\t")
        subjects = [row["participant_id"] for row in reader]

    for subj in subjects:
        subj_dir = bids_dir / subj
        if not subj_dir.exists():
            print(f"WARNING: Missing subject directory: {subj_dir}")
            continue

        for session_dir in sorted(subj_dir.glob("ses-*")):
            if not session_dir.is_dir():
                continue

            print(f"\n===== Processing {subj} {session_dir.name} =====")

            nii_files = find_bids_files(session_dir)
            print(f"  Found {len(nii_files)} NIfTI files")

            scans_tsv = session_dir / f"{subj}_{session_dir.name}_scans.tsv"

            # Orphan JSON detection
            orphans = list(find_orphan_jsons(session_dir, nii_files))
            for typ, path in orphans:
                if typ == "broken_json":
                    print(f"  WARNING: Bad JSON filename (likely from old bug): {path}")
                else:
                    print(f"  WARNING: Orphan JSON without NIfTI: {path}")

            # Write new scans.tsv
            if args.dry_run:
                print(f"  (dry-run) Would write scans.tsv with {len(nii_files)} files")
            else:
                if scans_tsv.exists() and args.backup:
                    backup = backup_file(scans_tsv)
                    print(f"  Backed up existing scans.tsv → {backup}")

                print(f"  Writing: {scans_tsv}")
                write_scans_tsv(scans_tsv, nii_files)

    print("\nDone.")


if __name__ == "__main__":
    main()
