#!/usr/bin/env python3
# Corrects BIDS error in order of entities within filenames (run/echo) 
# created using qp/bids-assistant: <https://bids-assistant.neurosift.app/chat> 
# set BIDS dataset path at bottom of script
# adjust dry-run option as needed 

import os
import re

def fix_entity_order(directory, dry_run=True):
    # Regex to identify filename pattern and entities
    pattern = re.compile(
        r'^(sub-[^_]+)'              # subject
        r'(_ses-[^_]+)?'             # optional session
        r'(_acq-[^_]+)?'             # optional acquisition
        r'(_echo-\d+)?'              # optional echo (can be out of order)
        r'(_run-\d+)?'               # optional run (can be out of order)
        r'(_[a-zA-Z0-9]+)'           # suffix like _T2w, _bold, etc.
        r'(\.nii\.gz|\.json|\.nii|\.bval|\.bvec)$'  # extension
    )

    for root, _, files in os.walk(directory):
        for fname in files:
            m = pattern.match(fname)
            if m:
                sub, ses, acq, echo, run, suffix, ext = m.groups()

                # Skip if either echo or run missing
                if not echo or not run:
                    continue

                # Check if echo appears before run (wrong order)
                if fname.find(echo) < fname.find(run):
                    new_fname = (
                        f"{sub}"
                        f"{ses or ''}"
                        f"{acq or ''}"
                        f"{run}"
                        f"{echo}"
                        f"{suffix}"
                        f"{ext}"
                    )
                    old_path = os.path.join(root, fname)
                    new_path = os.path.join(root, new_fname)

                    print(f"Would rename:\n  {old_path}\n  -> {new_path}")
                    if not dry_run:
                        os.rename(old_path, new_path)

if __name__ == "__main__":
    data_dir = "/Volumes/LaCie/Projects/elgan_dti/data/site-230"  # <-- set this to your dataset path
    fix_entity_order(data_dir, dry_run=False)  # Set dry_run=False to apply changes