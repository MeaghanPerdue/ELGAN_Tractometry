
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
