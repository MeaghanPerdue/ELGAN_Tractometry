
#!/usr/bin/env python3
# original by Christian Haselgrove
# Modified for ELGAN3 by Meaghan Perdue (July 2025; updated Oct 2025)
# Modified for GE by Meaghan Perdue (16 Jan 2026)
# This version includes robust missing-file handling for JSON, NIfTI, and TSV entries.

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

        tsv_path = session_dir / f'{subject}_{session}_scans.tsv'
        if not tsv_path.exists():
            print(f"WARNING: Missing scans.tsv: {tsv_path}")
            return

        with open(tsv_path) as f:
            reader = csv.DictReader(f, delimiter='\t')
            for row in reader:
                fname = row.get('filename')
                if not fname:
                    print(f"WARNING: Missing filename field in {tsv_path}, skipping row.")
                    continue

                try:
                    scan = Scan(session_dir, pathlib.Path(fname))
                    self._scans[fname] = scan
                except Exception as e:
                    print(f"WARNING: Could not load scan {fname}: {e}")

    def __getitem__(self, key):
        return self._scans[key]

    def __iter__(self):
        return iter(self._scans[key] for key in sorted(self._scans))

    def iter_subdir(self, subdir):
        return iter(scan for scan in self if scan['subdir'] == subdir)


class Scan:
    """Represents one scan and its JSON. Handles missing JSON robustly."""

    def __init__(self, session_dir, relative_path):
        self.path = session_dir / relative_path

        if not self.path.exists():
            print(f"WARNING: Missing NIfTI file: {self.path}")
            raise FileNotFoundError(self.path)

        self.session_path = session_dir.name / relative_path
        base_name = self.path.name[:-7]
        self._params = parse_file_name(self.path.name)
        self._params['subdir'] = self.path.parent.name

        self.json_path = self.path.parent / (base_name + '.json')
        if not self.json_path.exists():
            print(f"WARNING: Missing JSON sidecar for: {self.path.name}")
            self.data = None
        else:
            with open(self.json_path) as f:
                self.data = json.load(f)

        backup_name = base_name + '.json.' + BACKUP_EXTENSION
        self.json_backup_path = self.path.parent / backup_name

    def __repr__(self):
        return f"Scan('{self.path}')"

    def __getitem__(self, key):
        return self._params[key]


def parse_file_name(fname):
    d = {}
    for part in fname.split('.', 1)[0].split('_'):
        if '-' in part:
            name, value = part.split('-', 1)
            if name in ['run', 'echo']:
                value = int(value)
            d[name] = value
        else:
            d['type'] = part
    return d


def arg_bids_dir(arg):
    bids_dir = pathlib.Path(arg)
    if not bids_dir.exists() or not bids_dir.is_dir():
        raise argparse.ArgumentTypeError(f'{bids_dir}: not a valid directory')
    return bids_dir


def iter_sessions(bids_dir):
    """Yield all (subject, session, session_dir, scans) safely."""
    with open(bids_dir / 'participants.tsv') as f:
        reader = csv.DictReader(f, delimiter='\t')
        subjects = [row['participant_id'] for row in reader]

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


# -------------------------------------------------------------
# Parse arguments
# -------------------------------------------------------------
parser = argparse.ArgumentParser(description="Fix JSONs + rename PDT2 safely")
parser.add_argument('--check', '-c', action='store_true')
parser.add_argument('--diff', '-d', action='store_true')
parser.add_argument('--restore', '-r', action='store_true')
parser.add_argument('--dry-run', '-n', action='store_true')
parser.add_argument('bids_dir', type=arg_bids_dir)
args = parser.parse_args()

ensure_bidsignore(args.bids_dir)

# -------------------------------------------------------------
# STEP 1 — FIX JSONS (NO RENAMING YET)
# -------------------------------------------------------------
for subject, session, session_dir, scans in iter_sessions(args.bids_dir):
    print(subject, session)

    for scan in scans:
        print(f"    {scan}")

        if scan.data is None:
            print("        Skipping JSON modifications (missing JSON).")
            continue

        # Modify DWI JSONs
        if scan['subdir'] == 'dwi':
            print('        Updating DWI fields')

            scan.data['PhaseEncodingAxis'] = 'j'
            scan.data['PhaseEncodingDirection'] = 'j-'
            scan.data['TotalReadoutTime'] = 0.16218

            if not args.dry_run:
                shutil.move(scan.json_path, scan.json_backup_path)
                with open(scan.json_path, 'w') as f:
                    json.dump(scan.data, f, indent=4)
        else:
            print("        No changes.")


# -------------------------------------------------------------
# STEP 2 — UPDATE SCANS.TSV (SAFE HANDLING)
# -------------------------------------------------------------
def update_scans_tsv(bids_dir):
    bids_dir = pathlib.Path(bids_dir)
    for subject_dir in bids_dir.glob("sub-*"):
        for session_dir in subject_dir.glob("ses-*"):
            scans_tsv = session_dir / f"{subject_dir.name}_{session_dir.name}_scans.tsv"
            if not scans_tsv.exists():
                print(f"WARNING: Missing scans.tsv: {scans_tsv}")
                continue

            with open(scans_tsv, newline='') as f:
                reader = csv.DictReader(f, delimiter='\t')
                rows = list(reader)
                fieldnames = reader.fieldnames

            updated = False

            for row in rows:
                fname = row.get('filename')
                if not fname:
                    print(f"WARNING: Missing filename field in {scans_tsv}, skipping row.")
                    continue

                nifti = session_dir / fname
                json_sidecar = nifti.with_suffix('.json')

                if not nifti.exists():
                    print(f"WARNING: NIfTI listed in TSV not found: {nifti}")
                    continue
                if not json_sidecar.exists():
                    print(f"WARNING: JSON listed in TSV not found for: {nifti}")
                    continue

                if "acq-PDT2" in fname and "echo-" in fname and fname.endswith("_T2w.nii.gz"):
                    echo = "1" if "echo-1" in fname else "2" if "echo-2" in fname else None
                    if echo:
                        new_suffix = "PDw" if echo == "1" else "T2w"
                        row['filename'] = fname.replace(f"echo-{echo}_T2w", new_suffix)
                        updated = True

            if updated and not args.dry_run:
                with open(scans_tsv, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter='\t')
                    writer.writeheader()
                    writer.writerows(rows)
                print(f"Updated: {scans_tsv}")


update_scans_tsv(args.bids_dir)


# -------------------------------------------------------------
# STEP 3 — PDT2 RENAMING (AFTER TSV UPDATED)
# -------------------------------------------------------------
for subject, session, session_dir, scans in iter_sessions(args.bids_dir):
    print(subject, session)

    for scan in scans.iter_subdir('anat'):
        if scan._params.get('acq') == 'PDT2' and 'echo' in scan._params:

            echo = scan._params['echo']
            new_suffix = 'PDw' if echo == 1 else 'T2w'
            new_name = scan.path.name.replace(f"echo-{echo}_T2w", new_suffix)

            new_path = scan.path.parent / new_name
            new_json = new_path.with_suffix('.json')

            print(f"        Renaming {scan.path.name} → {new_name}")

            if not args.dry_run:
                if scan.path.exists():
                    scan.path.rename(new_path)
                else:
                    print(f"WARNING: NIfTI missing, cannot rename: {scan.path}")

                if scan.json_path.exists():
                    scan.json_path.rename(new_json)
                else:
                    print(f"WARNING: JSON missing, cannot rename: {scan.json_path}")


sys.exit(0)
