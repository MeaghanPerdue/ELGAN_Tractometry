#!/usr/bin/env python3
# original by Christian Haselgrove
# Modified for ELGAN3 by Meaghan Perdue (July 2025; updated Oct 2025)
# Modified for GE by Meaghan Perdue (16 Jan 2026)
# Updated with full missing-file handling and correct JSON renaming (no .nii.json)

import sys
import os
import pathlib
import argparse
import csv
import json
import shutil
import glob
import subprocess
import tempfile
from pathlib import Path

BACKUP_EXTENSION = 'bak'


def ensure_bidsignore(bids_dir):
    bids_dir = pathlib.Path(bids_dir)
    if not bids_dir.exists():
        bids_dir.mkdir(parents=True, exist_ok=True)

    bidsignore_path = bids_dir / '.bidsignore'
    if not bidsignore_path.exists():
        with open(bidsignore_path, 'w') as f:
            f.write('')
    return bidsignore_path


class Scans:
    """Load scans from scans.tsv with safe handling."""

    def __init__(self, subject, session, session_dir):
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
        return (scan for scan in self if scan["subdir"] == subdir)


class Scan:
    """Represents one scan + JSON with missing-file tolerance."""

    def __init__(self, session_dir, relative_path):
        self.path = session_dir / relative_path

        if not self.path.exists():
            print(f"WARNING: Missing NIfTI file: {self.path}")
            raise FileNotFoundError(self.path)

        self.session_path = session_dir.name / relative_path
        base = self.path.name[:-7]

        self._params = parse_file_name(self.path.name)
        self._params["subdir"] = self.path.parent.name

        self.json_path = self.path.parent / f"{base}.json"
        if not self.json_path.exists():
            print(f"WARNING: Missing JSON sidecar for {self.path.name}")
            self.data = None
        else:
            with open(self.json_path) as f:
                self.data = json.load(f)

        self.json_backup_path = self.path.parent / (f"{base}.json.{BACKUP_EXTENSION}")

    def __getitem__(self, key):
        return self._params[key]

    def __repr__(self):
        return f"Scan('{self.path}')"


def parse_file_name(fname):
    d = {}
    for part in fname.split(".", 1)[0].split("_"):
        if "-" in part:
            k, v = part.split("-", 1)
            if k in ["run", "echo"]:
                v = int(v)
            d[k] = v
        else:
            d["type"] = part
    return d


def arg_bids_dir(arg):
    bids_dir = pathlib.Path(arg)
    if not bids_dir.exists() or not bids_dir.is_dir():
        raise argparse.ArgumentTypeError(f"{bids_dir}: invalid directory")
    return bids_dir


def iter_sessions(bids_dir):
    """Safe generator of sessions."""

    part_path = bids_dir / "participants.tsv"
    if not part_path.exists():
        print(f"ERROR: Missing participants.tsv")
        return

    with open(part_path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        subjects = [row["participant_id"] for row in reader]

    for subject in subjects:
        subj_dir = bids_dir / subject
        if not subj_dir.exists():
            print(f"WARNING: Missing subject directory: {subj_dir}")
            continue

        for session_dir in subj_dir.iterdir():
            if not session_dir.is_dir():
                continue
            scans = Scans(subject, session_dir.name, session_dir)
            yield subject, session_dir.name, session_dir, scans


# ---------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------
parser = argparse.ArgumentParser(description="Fix BIDS JSONs + PDT2 rename + GE fields")
parser.add_argument("--check", "-c", action="store_true")
parser.add_argument("--diff", "-d", action="store_true")
parser.add_argument("--restore", "-r", action="store_true")
parser.add_argument("--dry-run", "-n", action="store_true")
parser.add_argument("bids_dir", type=arg_bids_dir)
args = parser.parse_args()

ensure_bidsignore(args.bids_dir)


# ---------------------------------------------------------
# STEP 1 — FIX JSONS (NO RENAMING YET)
# ---------------------------------------------------------
for subject, session, session_dir, scans in iter_sessions(args.bids_dir):
    print(subject, session)

    for scan in scans:
        print(f"    {scan}")

        if scan.data is None:
            print("        Skipping JSON edits: missing JSON")
            continue

        if scan["subdir"] == "dwi":
            print("        Updating DWI JSON fields")
            scan.data["PhaseEncodingAxis"] = "j"
            scan.data["PhaseEncodingDirection"] = "j-"
            scan.data["TotalReadoutTime"] = 0.16218

            if not args.dry_run:
                shutil.move(scan.json_path, scan.json_backup_path)
                with open(scan.json_path, "w") as f:
                    json.dump(scan.data, f, indent=4)
        else:
            print("        No DWI changes")


# ---------------------------------------------------------
# STEP 2 — UPDATE scans.tsv (SAFE)
# ---------------------------------------------------------
def update_scans_tsv(bids_dir):
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

                nifti = session_dir / fname

                if "acq-PDT2" in fname and "echo-" in fname and fname.endswith("_T2w.nii.gz"):
                    echo = "1" if "echo-1" in fname else "2" if "echo-2" in fname else None
                    if echo:
                        new_suffix = "PDw" if echo == "1" else "T2w"
                        row["filename"] = fname.replace(f"echo-{echo}_T2w", new_suffix)
                        changed = True

            if changed and not args.dry_run:
                with open(scans_tsv, "w") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
                    writer.writeheader()
                    writer.writerows(rows)
                print(f"Updated: {scans_tsv}")


update_scans_tsv(args.bids_dir)


# ---------------------------------------------------------
# STEP 3 — PDT2 RENAMING (AFTER TSV FIX)
# ---------------------------------------------------------
for subject, session, session_dir, scans in iter_sessions(args.bids_dir):
    print(subject, session)

    for scan in scans.iter_subdir("anat"):
        if scan._params.get("acq") == "PDT2" and "echo" in scan._params:

            echo = scan._params["echo"]
            new_suffix = "PDw" if echo == 1 else "T2w"
            new_name = scan.path.name.replace(f"echo-{echo}_T2w", new_suffix)

            new_path = scan.path.parent / new_name
            # FIX FOR .nii.json BUG — explicit json rename:
            new_json = Path(str(new_path).replace(".nii.gz", ".json"))

            print(f"        Renaming {scan.path.name} → {new_name}")

            if not args.dry_run:
                if scan.path.exists():
                    scan.path.rename(new_path)
                else:
                    print(f"WARNING: Missing NIfTI, cannot rename: {scan.path}")

                if scan.json_path.exists():
                    scan.json_path.rename(new_json)
                else:
                    print(f"WARNING: Missing JSON, cannot rename: {scan.json_path}")

# ---------------------------------------------------------
# STEP 4 - COPY AND RENAME MASTER BVAL AND BVEC FILES ALONGSIDE SUBJECT-LEVEL DWIs
# ---------------------------------------------------------
# Paths to master files (in your BIDS root!)
master_bval = args.bids_dir / 'dwi.bval'
master_bvec = args.bids_dir / 'dwi.bvec'

if not master_bval.exists() or not master_bvec.exists():
    print(f"ERROR: Missing master dwi.bval or dwi.bvec in {args.bids_dir}")
else:
    for subject, session, session_dir, scans in iter_sessions(args.bids_dir):
        if session != "ses-03":
            continue  # restrict to ses-03 only

        dwi_dir = session_dir / "dwi"
        if not dwi_dir.exists():
            print(f"WARNING: No dwi dir for {subject} {session}: {dwi_dir}")
            continue

        # Find all DWI NIfTI files
        for nii_file in dwi_dir.glob("*.nii*"):
            # Get base filename (without extension)
            base = nii_file.name.replace(".nii.gz", "").replace(".nii", "")
            bval_out = dwi_dir / f"{base}.bval"
            bvec_out = dwi_dir / f"{base}.bvec"

            if args.dry_run:
                print(f"[dry-run] Would copy {master_bval} to {bval_out}")
                print(f"[dry-run] Would copy {master_bvec} to {bvec_out}")
            else:
                shutil.copy2(master_bval, bval_out)
                shutil.copy2(master_bvec, bvec_out)
                print(f"Copied {master_bval} to {bval_out}")
                print(f"Copied {master_bvec} to {bvec_out}")


sys.exit(0)
