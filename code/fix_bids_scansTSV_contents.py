#!/usr/bin/env python3
# Read scans.tsv files for each subject/session in BIDS dataset, check actual file contents, and fix scans.tsv to match
# created using qp/bids-assistant: <https://bids-assistant.neurosift.app/chat> 
# set BIDS dataset path at bottom of script
# adjust dry-run option as needed 

import os
import csv
import re

def fix_scans_tsv(bids_root):
    """
    Iterates through BIDS dataset directory (bids_root),
    finds all scans.tsv files matching the pattern:
    sub-<label>/ses-<label>/sub-<label>_ses-<label>_scans.tsv
    and rewrites them to contain exactly the imaging files present
    under the corresponding subject/session directory,
    removing duplicate entries.
    """

    # Allowed imaging file extensions to include in scans.tsv
    valid_exts = {'.nii', '.nii.gz', '.bval', '.bvec'}

    # Pattern for scans.tsv filename: sub-<label>_ses-<label>_scans.tsv, ignoring case
    scans_filename_pattern = re.compile(r'^sub-[a-zA-Z0-9]+_ses-[a-zA-Z0-9]+_scans\.tsv$', re.IGNORECASE)

    for root, dirs, files in os.walk(bids_root):
        for filename in files:
            if scans_filename_pattern.match(filename):
                scans_path = os.path.join(root, filename)
                print(f"Fixing {scans_path}")

                base_dir = root  # scans.tsv is inside the relevant subject/session directory

                # Collect unique imaging files under the base_dir recursively
                imaging_files = set()
                for dirpath, _, dirfiles in os.walk(base_dir):
                    for f in dirfiles:
                        ext = f.lower()
                        if any(f.lower().endswith(suff) for suff in valid_exts):
                            # Exclude scans.tsv itself to avoid recursion
                            if f == filename:
                                continue
                            full_path = os.path.join(dirpath, f)
                            rel_path = os.path.relpath(full_path, base_dir)
                            imaging_files.add(rel_path)

                imaging_files = sorted(imaging_files)

                header = ['filename', 'acq_time', 'operator', 'randstr']

                with open(scans_path, 'w', newline='') as tsvfile:
                    writer = csv.writer(tsvfile, delimiter='\t')
                    writer.writerow(header)
                    for img_file in imaging_files:
                        writer.writerow([img_file, 'n/a', 'n/a', 'n/a'])

                print(f"Fixed {scans_path}: wrote {len(imaging_files)} unique file entries\n")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fix scans.tsv files in BIDS dataset")
    parser.add_argument('bids_root', type=str, help="Root directory of BIDS dataset")

    args = parser.parse_args()
    fix_scans_tsv(args.bids_root)