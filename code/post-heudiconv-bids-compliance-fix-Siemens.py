#!/usr/bin/env python3
# original by Christian Haselgrove
# Modified for ELGAN3 by Meaghan Perdue 10 July 2025, added PDT2 handling Oct 2025
# This version omits changes to the .json sidecars, since the metadata from Siemens DICOMs headers is used to populate the field in a BIDS-compliant way

import sys
import os
import pathlib
import argparse
import csv
import json
import shutil
import subprocess
import tempfile
import re

from pathlib import Path

BACKUP_EXTENSION = 'bak'


def ensure_bidsignore(bids_dir):
    bids_dir = pathlib.Path(bids_dir)
    if not bids_dir.exists():
        print(f"Creating missing BIDS directory: {bids_dir}")
        bids_dir.mkdir(parents=True, exist_ok=True)

    bidsignore_path = bids_dir / '.bidsignore'
    if not bidsignore_path.exists():
        print(' .bidsignore not found, creating it')
        try:
            with open(bidsignore_path, 'w') as f:
                f.write('')
        except Exception as e:
            print(f"Failed to create .bidsignore: {e}")
    return bidsignore_path


class Scans:

    """A collection of scans.

    A Scans object is indexed by scan number (like a dictionary)
    but iteration over a Scans object will yield Scan objects (like
    a sequence).

    Scan numbers are integers.
    """

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
        return iter(scan for scan in self if scan['subdir'] == subdir)

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

def arg_bids_dir(arg):
    """argparse argument type for a BIDS directory."""
    bids_dir = pathlib.Path(arg)
    if not bids_dir.exists():
        raise argparse.ArgumentTypeError(f'{bids_dir}: does not exist')
    if not bids_dir.is_dir():
        raise argparse.ArgumentTypeError(f'{bids_dir}: not a directory')
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

progname = os.path.basename(sys.argv[0])

description = 'Fix BIDS JSON files for the ELGAN3 DWI data.'
epilog = f"""
Changes to BIDS file names based on echo and updates scans.tsv files:

    anat: 

        Check filenames of dual-echo TSE scans for correct BIDS suffixes
        based on echo-1 or echo-2. 
        echo-1 = PDw (shorter TE)
        echo-2 = T2w (longer TE)


JSON files are backed up to .{BACKUP_EXTENSION} before being modified.

-r can be used to restore backups, and -n can be used for a dry run 
(check only and don't write changes).

-d can be used to show the difference between modified and backup files.

.bidsignore is updated to include "*.bak" when this script is run.
"""
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

# Ensure .bidsignore exists before anything else
ensure_bidsignore(args.bids_dir)

# ---------------------------------------------------------
# STEP 1 — UPDATE scans.tsv (SAFE)
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

# ---------------------------------------------------------
# STEP 2 — PDT2 RENAMING (AFTER TSV FIX)
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

update_scans_tsv(args.bids_dir)

sys.exit(0)

# eof
