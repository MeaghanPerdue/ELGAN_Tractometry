#!/usr/bin/env python3
# original by Christian Haselgrove
# Modified for ELGAN3 by Meaghan Perdue 10 July 2025, added PDT2 handling Oct 2025
# this is the same as fix_bids_json_elgan3_dwi_PDT2_v3, just renamed for more general workflow

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
        with open(session_dir / f'{subject}_{session}_scans.tsv') as f:
            reader = csv.DictReader(f, delimiter='\t')
            for row in reader:
                scan = Scan(session_dir, pathlib.Path(row['filename']))
                assert row['filename'] not in self._scans
                self._scans[row['filename']] = scan
        return

    def __getitem__(self, key):
        return self._scans[key]

    def __iter__(self):
        return iter(self._scans[key] for key in sorted(self._scans))

    def iter_subdir(self, subdir):
        return iter(scan for scan in self if scan['subdir'] == subdir)

class Scan:

    """A scan.

    A Scan object can be used as a mapping, returning elements of its file 
    name, so for sub-BB03601_ses-1_acq-rsfmri_dir-AP_run-34_epi.nii.gz, 
    scan['acq'] == 'rsfmri'.

    Attributes are:

        path: the path to the data file.

        session_path: the path to the data file relative to the subject 
        directory (starts with ses- and is appropriate for IntendedFor).

        json_path: the path to the associated JSON sidecar file.

        data: the contents of the JSON sidecar.

        json_backup_path: the path to the backup JSON file.
    """

    def __init__(self, session_dir, relative_path):
        self.path = session_dir / relative_path
        self.session_path = session_dir.name / relative_path
        assert self.path.name.endswith('.nii.gz')
        base_name = self.path.name[:-7]
        self._params = parse_file_name(self.path.name)
        self._params['subdir'] = self.path.parent.name
        self.json_path = self.path.parent / (base_name + '.json')
        with open(self.json_path) as f:
            self.data = json.load(f)
        backup_name = (base_name + '.json.' + BACKUP_EXTENSION)
        self.json_backup_path = self.path.parent / backup_name
        return

    def __repr__(self):
        return f"Scan('{self.path}')"

    # def __str__(self):
    #     return f'Scan {self["run"]} ({self["subdir"]})'

    def __getitem__(self, key):
        return self._params[key]

def arg_bids_dir(arg):
    """argparse argument type for a BIDS directory."""
    bids_dir = pathlib.Path(arg)
    if not bids_dir.exists():
        raise argparse.ArgumentTypeError(f'{bids_dir}: does not exist')
    if not bids_dir.is_dir():
        raise argparse.ArgumentTypeError(f'{bids_dir}: not a directory')
    return bids_dir

def iter_sessions(bids_dir):
    """Iterate over sessions in the BIDS directory."""
    with open(bids_dir / 'participants.tsv') as f:
        reader = csv.DictReader(f, delimiter='\t')
        subjects = [ row['participant_id'] for row in reader ]
    for subject in subjects:
        for session_dir in (bids_dir / subject).iterdir():
            if not session_dir.is_dir():
                continue  # Skip files like .DS_Store
        scans = Scans(subject, session_dir.name, session_dir)
        yield subject, session_dir.name, session_dir, scans
    return


def parse_file_name(fname):
    """Decompose a BIDS filename into a mapping.

    Example:

        Given: sub-BB03601_ses-1_acq-rsfmri_dir-AP_run-34_epi.nii.gz, this 
        will return:

            {
                'sub': 'BB03601', 
                'ses': '1', 
                'acq': 'rsfmri',
                'dir': 'AP', 
                'run': '34', 
                'type': 'epi'
            }

    """
    d = {}
    for part in fname.split('.', 1)[0].split('_'):
        if '-' in part:
            name, value = part.split('-', 1)
            if name == 'run' or name == 'echo':
                value = int(value)
            d[name] = value
        else:
            d['type'] = part
    return d

progname = os.path.basename(sys.argv[0])

description = 'Fix BIDS JSON files for the ELGAN3 DWI data.'
epilog = f"""
Changes to JSON files are made to fix missing info from Philips DICOMS.  Checks 
and changes are:

    anat: 

        Check filenames of dual-echo TSE scans for correct BIDS suffixes
        based on echo-1 or echo-2. 
        echo-1 = PDw (shorter TE)
        echo-2 = T2w (longer TE)

    fmaps:
    
        Check that B0FieldIdentifier is not set, then set it to 
        "pepolar_ABCD".                                

        Check that PhaseEncodingDirection is not set and that 
        PhaseEncodingAxis is "j", then set PhaseEncodingDirection
        according to dir. (AP="j-", PA="j")

        Set IntendedFor according to acq.

        Check that TotalReadoutTime is not set, then set it to the 
        value of EstimatedTotalReadoutTime.

    dwi:

        Check that PhaseEncodingDirection is not set and that 
        PhaseEncodingAxis is "j", then set PhaseEncodingDirection
        according to "j-".

        Check that TotalReadoutTime is not set, then set it to the 
        value of EstimatedTotalReadoutTime.


The checks encode assumptions about the data, so if a check fails, 
the script terminates.

JSON files are backed up to .{BACKUP_EXTENSION} before being modified.

-r can be used to restore backups, and -n can be used for a dry run 
(check only and don't write changes).

-d can be used to show the difference between modified and backup files.

.bidsignore is updated to include "*.bak" when this script is run.
"""
parser = argparse.ArgumentParser(
    progname, 
    description=description, 
    epilog=epilog, 
    formatter_class=argparse.RawDescriptionHelpFormatter
)
parser.add_argument(
    '--check', 
    '-c', 
    action='store_true', 
    help='check only (don\'t write)'
)
parser.add_argument(
    '--diff', 
    '-d', 
    action='store_true', 
    help='show JSON diffs'
)
parser.add_argument(
    '--restore', 
    '-r', 
    action='store_true', 
    help='restore original JSONs'
)
parser.add_argument(
    '--dry-run', 
    '-n', 
    action='store_true', 
    help='don\'t write changes'
)
parser.add_argument(
    'bids_dir', 
    type=arg_bids_dir, 
    help='BIDS directory'
)

args = parser.parse_args()


# Ensure .bidsignore exists before anything else
ensure_bidsignore(args.bids_dir)

for subject, session, session_dir, scans in iter_sessions(args.bids_dir):
    print(subject, session)
    # Rename PDT2 anat files 
    for scan in scans.iter_subdir('anat'):
        if scan['acq'] == 'PDT2' and 'echo' in scan._params:
            echo = scan['echo']
            new_suffix = 'PDw' if echo == 1 else 'T2w' if echo == 2 else None
            if new_suffix:
                new_name = scan.path.name.replace(f"echo-{echo}_T2w", f"{new_suffix}")
                new_path = scan.path.parent / new_name
                new_json_path = Path(str(new_path).replace('.nii.gz', '.json'))

                print(f"        Renaming {scan.path.name} → {new_name}")
                if not args.dry_run:
                    scan.path.rename(new_path)
                    scan.json_path.rename(new_json_path)

    if args.diff:
        for scan in scans:
            print(f'--- {scan} --------------------')
            if scan.json_backup_path.exists():
                # The backup file was the original written by heudiconv.  
                # The (modified) data file was written by this script 
                # using json.dump().  To use diff, we need to format the 
                # original to match the modified file.
                with open(scan.json_backup_path) as f:
                    data = json.load(f)
                with tempfile.NamedTemporaryFile(mode='w') as f:
                    json.dump(data, f, indent=4)
                    f.flush()
                    cmd = ['diff', f.name, scan.json_path.as_posix()]
                    subprocess.run(cmd)
            else:
                print('No backup')
            pass
    elif args.restore:       
        for scan in scans:
            if scan.json_backup_path.exists():
                if args.dry_run:
                    print(f'    {scan}: Restoring (not really: dry run)')
                else:
                    print(f'    {scan}: Restoring')
                    shutil.move(scan.json_backup_path, scan.json_path)
            else:
                print(f'    {scan}: No backup')
        if args.dry_run:
            print('    .bidsignore: Removing *.bak (not really: dry run)')
        else:
            print('    .bidsignore: Removing *.bak')
            with open(args.bids_dir / '.bidsignore') as f:
                ignore = [ line.rstrip('\n') for line in f.readlines() ]
            if '*.bak' in ignore:
                ignore.remove('*.bak')
                with open(args.bids_dir / '.bidsignore', 'w') as f:
                    for line in ignore:
                        print(line, file=f)        
    else:
        # Check for backup files first and stop if any is found.
        backups = [ 
            s.json_backup_path for s in scans if s.json_backup_path.exists()
        ]
        if backups:
            for backup in backups:
                print(f'{progname}: {backup} exists', file=sys.stderr)
            sys.exit(1)
        for scan in scans:
            print(f'    {scan}')
            if scan['subdir'] == 'fmap':
                print('        Setting B0FieldIdentifier')
                if 'B0FieldIdentifier' not in scan.data:
                    print(' Setting B0FieldIdentifier')
                    scan.data['B0FieldIdentifier'] = 'pepolar_ABCD'
                else:
                    print(' B0FieldIdentifier already set, skipping')
                print('        Setting PhaseEncodingDirection')
                if 'PhaseEncodingDirection' not in scan.data:
                    assert scan['dir'] in ['AP', 'PA'] 
                    if scan['dir'] == 'AP':
                        scan.data['PhaseEncodingDirection'] = 'j-'
                        scan.data['IntendedFor'] = [
                            s.session_path.as_posix()
                            for s in scans.iter_subdir('dwi')
                            if 'acq' in s._params and s['acq'] in ['ABCD1', 'ABCD2']
                        ]
                    if scan['dir'] == 'PA':
                        scan.data['PhaseEncodingDirection'] = 'j'
                        scan.data['IntendedFor'] = [
                            s.session_path.as_posix()
                            for s in scans.iter_subdir('dwi')
                            if 'acq' in s._params and s['acq'] in ['ABCD1', 'ABCD2']
                        ]
                else:
                    print(' PhaseEncodingDirection already set, skipping')
            if scan['subdir'] == 'dwi':
                print('        Setting PhaseEncodingDirection')
                #assert 'PhaseEncodingDirection' not in scan.data
                assert scan.data['PhaseEncodingAxis'] == 'j'
                scan.data['PhaseEncodingDirection'] = 'j-' 
            if scan['subdir'] in ['fmap', 'dwi']:
                print('        Setting TotalReadoutTime')
                #assert 'TotalReadoutTime' not in scan.data
                scan.data['TotalReadoutTime'] = \
                        scan.data['EstimatedTotalReadoutTime']
            if scan['subdir'] in ['fmap', 'dwi']:
                if args.dry_run:
                    print(f'        Writing (not really: dry run)')
                else:
                    print(f'        Writing')
                    shutil.move(scan.json_path, scan.json_backup_path)
                    with open(scan.json_path, 'w') as f:
                        json.dump(scan.data, f, indent=4)
            else:
                print(f'        No changes')
        if args.dry_run:
            print('    .bidsignore: Adding *.bak (not really: dry run)')
        else:
            print('    .bidsignore: Adding *.bak')
            with open(args.bids_dir / '.bidsignore') as f:
                ignore = [ line.rstrip('\n') for line in f.readlines() ]
            if '*.bak' not in ignore:
                ignore.append('*.bak')
                with open(args.bids_dir / '.bidsignore', 'w') as f:
                    for line in ignore:
                        print(line, file=f)

def update_scans_tsv(bids_dir):
    bids_dir = pathlib.Path(bids_dir)
    for subject_dir in bids_dir.glob("sub-*"):
        for session_dir in subject_dir.glob("ses-*"):
            scans_tsv = session_dir / f"{subject_dir.name}_{session_dir.name}_scans.tsv"
            if not scans_tsv.exists():
                continue

            with open(scans_tsv, newline='') as f:
                reader = csv.DictReader(f, delimiter='	')
                rows = list(reader)
                fieldnames = reader.fieldnames

            updated = False
            for row in rows:
                fname = row['filename']
                if "acq-PDT2" in fname and "echo-" in fname and fname.endswith("_T2w.nii.gz"):
                    echo = "1" if "echo-1" in fname else "2" if "echo-2" in fname else None
                    if echo:
                        new_suffix = "PDw" if echo == "1" else "T2w"
                        new_fname = fname.replace(f"echo-{echo}_T2w", f"{new_suffix}")
                        row['filename'] = new_fname
                        updated = True

            if updated:
                with open(scans_tsv, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter='	')
                    writer.writeheader()
                    writer.writerows(rows)
                print(f"Updated: {scans_tsv}")
            else:
                print(f"No changes needed: {scans_tsv}")

update_scans_tsv(args.bids_dir)

sys.exit(0)

# eof
