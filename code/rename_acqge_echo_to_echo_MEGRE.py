#!/usr/bin/env python3
"""
rename_acqge_echo_to_echo_MEGRE.py

Created with OpenAI GPT5-mini 15 Jan 2026

Rename BIDS files whose basename matches "*_acq-ge_echo-<echo>_T2w(.nii or .nii.gz)"
to "*_echo-<echo>_MEGRE(.nii or .nii.gz)", preserving the same echo token,
and update scans.tsv / *_scans.tsv entries accordingly.

Example:
  sub-01_ses-01_acq-ge_echo-1_T2w.nii.gz  ->
    sub-01_ses-01_echo-1_MEGRE.nii.gz

Behavior:
- Finds .nii.gz and .nii files anywhere under the dataset root.
- For filenames whose stem matches "(.*)_acq-ge_echo-(.*)_T2w", renames them to
  "{prefix}_echo-{echo}_MEGRE" (no trailing "_T2w").
- Renames the corresponding .json sidecar (expects same base name + .json).
- Updates scans files named "scans.tsv" or matching "*_scans.tsv" to use the new basenames
  (preserving any path prefixes).
- Supports --dry-run to preview changes and writes a CSV log (default dir_rename_acqge_log.csv).
- Creates timestamped .bak copies of scans files before editing (unless --no-backup-scans).
- Skips files where target already exists or sidecar is missing.

Usage:
  Dry-run (recommended):
    python3 rename_acqge_echo_to_echo_MEGRE.py --root . --dry-run

  Real run:
    python3 rename_acqge_echo_to_echo_MEGRE.py --root .
"""
import argparse
import csv
import os
import re
import shutil
from datetime import datetime
import fnmatch

RE_PATTERN = re.compile(r"^(?P<prefix>.*)_acq-ge_echo-(?P<echo>.+)_T2w$")

def find_scans_tsvs(root):
    """Return list of paths to scans files: 'scans.tsv' and '*_scans.tsv'."""
    tsvs = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn == "scans.tsv" or fn.endswith("_scans.tsv") or fnmatch.fnmatch(fn, "*_scans.tsv"):
                tsvs.append(os.path.join(dirpath, fn))
    return tsvs

def replace_basename_in_path_value(val, old_basename, new_basename):
    """
    Replace trailing occurrence of old_basename in val with new_basename, preserving any prefix.
    Returns (changed_bool, new_value)
    """
    if not val:
        return False, val
    # exact match
    if val == old_basename:
        return True, new_basename
    # ends with slash + basename
    if val.endswith("/" + old_basename):
        prefix = val[:len(val) - len(old_basename)]
        return True, prefix + new_basename
    # windows backslash
    if val.endswith("\\" + old_basename):
        prefix = val[:len(val) - len(old_basename)]
        return True, prefix + new_basename
    # if basename matches, replace last occurrence
    if os.path.basename(val) == old_basename:
        idx = val.rfind(old_basename)
        if idx != -1:
            new_val = val[:idx] + new_basename + val[idx + len(old_basename):]
            return True, new_val
    return False, val

def update_scans_tsv(tsv_path, old_basename, new_basename, dry_run, backup=True):
    """
    Update filename column in a scans TSV. Returns (changed_bool, count_replacements).
    - Detects header 'filename' (case-insensitive) for column to update; otherwise uses first column.
    - Creates timestamped .bak if backup is True and not dry_run.
    """
    try:
        with open(tsv_path, 'r', encoding='utf-8', newline='') as f:
            text = f.read()
    except Exception as e:
        print(f"Warning: cannot read {tsv_path}: {e}")
        return False, 0
    if old_basename not in text:
        return False, 0

    if not dry_run and backup:
        bak = tsv_path + ".bak." + datetime.now().strftime("%Y%m%dT%H%M%S")
        try:
            shutil.copy2(tsv_path, bak)
        except Exception as e:
            print(f"Warning: failed to create backup {bak}: {e}")

    with open(tsv_path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.reader(f, delimiter='\t')
        rows = list(reader)

    if not rows:
        return False, 0

    header = rows[0]
    if any(h.lower() == 'filename' for h in header):
        filename_col = next(i for i, h in enumerate(header) if h.lower() == 'filename')
        start_row = 1
    else:
        filename_col = 0
        start_row = 0

    updated = 0
    for i in range(start_row, len(rows)):
        if len(rows[i]) <= filename_col:
            continue
        val = rows[i][filename_col]
        changed, new_val = replace_basename_in_path_value(val, old_basename, new_basename)
        if changed:
            rows[i][filename_col] = new_val
            updated += 1

    if updated and not dry_run:
        try:
            with open(tsv_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f, delimiter='\t')
                for r in rows:
                    writer.writerow(r)
        except Exception as e:
            print(f"ERROR writing updated {tsv_path}: {e}")
            return False, 0

    return (updated > 0), updated

def path_base_json_for_nii(nii_path):
    if nii_path.endswith(".nii.gz"):
        return nii_path[:-7]
    else:
        return os.path.splitext(nii_path)[0]

def is_nifti_filename(fn):
    return fn.endswith(".nii.gz") or fn.endswith(".nii")

def make_new_basename_from_stem(stem):
    """
    If stem matches RE_PATTERN, return the new stem:
      "{prefix}_echo-{echo}_MEGRE"
    Otherwise return None.
    """
    m = RE_PATTERN.match(stem)
    if not m:
        return None
    prefix = m.group('prefix')
    echo = m.group('echo')
    return f"{prefix}_echo-{echo}_MEGRE"

def main():
    p = argparse.ArgumentParser(description="Rename *_acq-ge_echo-<echo>_T2w -> *_echo-<echo>_MEGRE and update scans TSVs")
    p.add_argument("--root", "-r", default=".", help="dataset root (default .)")
    p.add_argument("--dry-run", action="store_true", help="print planned changes but do not rename files or modify scans TSVs")
    p.add_argument("--log", default="dir_rename_acqge_log.csv", help="CSV log of changes")
    p.add_argument("--no-backup-scans", action="store_true", help="do not create a .bak before modifying scans TSVs")
    args = p.parse_args()

    root = args.root
    scans_tsvs = find_scans_tsvs(root)
    log_entries = []

    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if not is_nifti_filename(fn):
                continue

            # derive stem (without extension)
            if fn.endswith(".nii.gz"):
                stem = fn[:-7]
                ext = ".nii.gz"
            else:
                stem = os.path.splitext(fn)[0]
                ext = ".nii"

            new_stem = make_new_basename_from_stem(stem)
            if not new_stem:
                continue

            new_fn = new_stem + ext
            nii_path = os.path.join(dirpath, fn)
            new_path = os.path.join(dirpath, new_fn)
            base = path_base_json_for_nii(nii_path)
            json_path = base + ".json"
            new_json = path_base_json_for_nii(new_path) + ".json"

            print(f"{'DRY:' if args.dry_run else 'DO:'} {nii_path} -> {new_path}")

            if args.dry_run:
                log_entries.append([nii_path, new_path, fn, new_fn, json_path, new_json, "dry-run"])
                continue

            # check sidecar exists
            if not os.path.exists(json_path):
                print(f"Skipping (no JSON sidecar): {nii_path}")
                log_entries.append([nii_path, "", fn, "", json_path, "", "no-json"])
                continue

            # safety: skip if target exists
            if os.path.exists(new_path) or os.path.exists(new_json):
                print(f"ERROR: target already exists, skipping: {new_path} or {new_json}")
                log_entries.append([nii_path, new_path, fn, new_fn, json_path, new_json, "target-exists"])
                continue

            # perform rename
            try:
                os.rename(nii_path, new_path)
                os.rename(json_path, new_json)
            except Exception as e:
                print(f"ERROR renaming {nii_path} or its JSON: {e}")
                log_entries.append([nii_path, new_path, fn, new_fn, json_path, new_json, f"rename-error:{e}"])
                continue

            # update scans TSV files
            total_updated = 0
            for tsv in scans_tsvs:
                changed, count = update_scans_tsv(tsv, fn, new_fn, dry_run=False, backup=not args.no_backup_scans)
                if changed:
                    total_updated += count

            log_entries.append([nii_path, new_path, fn, new_fn, json_path, new_json, total_updated])

    # write log CSV
    with open(args.log, 'w', encoding='utf-8', newline='') as lf:
        writer = csv.writer(lf)
        writer.writerow(["old_nii_path", "new_nii_path", "old_basename", "new_basename", "old_json", "new_json", "scans_tsv_replacements_or_status"])
        for r in log_entries:
            writer.writerow(r)

    print("Done. Log written to", args.log)

if __name__ == "__main__":
    main()