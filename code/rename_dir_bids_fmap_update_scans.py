#!/usr/bin/env python3
"""
rename_dir_bids_fmap_update_scans.py

created with OpenAI GPT-5-mini via ChanChat 14Jan2026

Insert dir-* into BIDS .nii.gz filenames based on PhaseEncodingDirection for files located in fmap/ directories,
and update scans.tsv and *_scans.tsv files (e.g., sub-XX_ses-YY_scans.tsv) to point to the renamed files.

Main improvements vs. previous version:
- Finds scans files named either "scans.tsv" or matching "*_scans.tsv".
- Replaces the basename portion in the filename column robustly (handles bare basenames, prefixed paths, and trailing variants).
- Keeps backups of modified scans files (timestamped) unless --no-backup-scans is given.
- Dry-run mode available.

Usage:
  Dry run (recommended):
    python3 rename_dir_bids_fmap_update_scans.py --root . --dry-run

  Real run:
    python3 rename_dir_bids_fmap_update_scans.py --root .

  Custom mapping:
    mapping.json -> {"j-":"AP","j":"PA"}
    python3 rename_dir_bids_fmap_update_scans.py --root . --mapping-file mapping.json --dry-run
"""
import argparse
import csv
import json
import os
import shutil
from datetime import datetime
import fnmatch

DEFAULT_MAPPING = {"j-": "AP", "j": "PA", "i-": "RL", "i": "LR", "k-": "IS", "k": "SI"}

def load_mapping(path):
    if not path:
        return DEFAULT_MAPPING.copy()
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    merged = DEFAULT_MAPPING.copy()
    merged.update(data)
    return merged

def find_scans_tsvs(root):
    """
    Return list of paths to scans files:
      - files named exactly 'scans.tsv'
      - files matching '*_scans.tsv' (e.g., sub-01_ses-02_scans.tsv)
    """
    tsvs = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn == "scans.tsv" or fn.endswith("_scans.tsv") or fnmatch.fnmatch(fn, "*_scans.tsv"):
                tsvs.append(os.path.join(dirpath, fn))
    return tsvs

def replace_basename_in_path_value(val, old_basename, new_basename):
    """
    Replace the trailing occurrence of old_basename in val with new_basename, preserving any prefix.
    Examples:
      - "sub-01_ses-01_task-rest_bold.nii.gz" -> replaced if matches old_basename
      - "fmap/sub-01_ses-01_acq-sbref_epi.nii.gz" -> replaced prefix kept
      - "./fmap/sub-01_ses-01_acq-sbref_epi.nii.gz" -> replaced
    Returns (changed_bool, new_value)
    """
    if not val:
        return False, val
    # exact match
    if val == old_basename:
        return True, new_basename
    # if it ends with old_basename (handles prefixed path)
    if val.endswith("/" + old_basename):
        prefix = val[:len(val) - len(old_basename)]
        return True, prefix + new_basename
    # handle backslash windows paths just in case
    if val.endswith("\\" + old_basename):
        prefix = val[:len(val) - len(old_basename)]
        return True, prefix + new_basename
    # if basename matches (e.g., there may be query strings or other noise), replace the last occurrence of old_basename
    if os.path.basename(val) == old_basename:
        # find last occurrence of old_basename and replace it
        idx = val.rfind(old_basename)
        if idx != -1:
            new_val = val[:idx] + new_basename + val[idx + len(old_basename):]
            return True, new_val
    # not recognized form
    return False, val

def update_scans_tsv(tsv_path, old_basename, new_basename, dry_run, backup=True):
    """
    Update filename column in a scans TSV. Returns (changed_bool, count_replacements).
    - Detects header column named 'filename' (case-insensitive) and uses that column.
    - Otherwise uses first column as filename.
    - Makes a timestamped .bak if backup is True and not dry_run.
    """
    # quick skip if old_basename not present at all
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

    # read as TSV
    with open(tsv_path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.reader(f, delimiter='\t')
        rows = list(reader)

    if not rows:
        return False, 0

    # find filename column if header exists
    filename_col = 0
    start_row = 0
    header = rows[0]
    if any(h.lower() == 'filename' for h in header):
        filename_col = next(i for i, h in enumerate(header) if h.lower() == 'filename')
        start_row = 1
    else:
        # No header: assume first column is filename
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
        base = nii_path[:-7]
    else:
        base = os.path.splitext(nii_path)[0]
    return base

def main():
    p = argparse.ArgumentParser(description="Insert dir-* into BIDS filenames in fmap/ based on PhaseEncodingDirection and update scans/*.tsv")
    p.add_argument("--root", "-r", default=".", help="dataset root (default .)")
    p.add_argument("--mapping-file", "-m", help="optional JSON file specifying mapping from PhaseEncodingDirection -> dir label")
    p.add_argument("--dry-run", action="store_true", help="print planned changes but do not rename files or modify scans TSVs")
    p.add_argument("--log", default="dir_rename_fmap_log.csv", help="CSV log of changes")
    p.add_argument("--no-backup-scans", action="store_true", help="do not create a .bak before modifying scans TSVs")
    args = p.parse_args()

    mapping = load_mapping(args.mapping_file)
    root = args.root
    scans_tsvs = find_scans_tsvs(root)
    log_entries = []

    for dirpath, _, filenames in os.walk(root):
        # only process files under a directory named "fmap"
        if 'fmap' not in dirpath.split(os.sep):
            continue
        for fn in filenames:
            if not fn.endswith(".nii.gz"):
                continue
            if "_dir-" in fn:
                continue

            nii_path = os.path.join(dirpath, fn)
            base = path_base_json_for_nii(nii_path)
            json_path = base + ".json"
            if not os.path.exists(json_path):
                print(f"Skipping (no JSON): {nii_path}")
                log_entries.append([nii_path, "", fn, "", json_path, "", "no-json"])
                continue

            try:
                with open(json_path, 'r', encoding='utf-8') as jf:
                    jdata = json.load(jf)
            except Exception as e:
                print(f"Warning: failed to read JSON {json_path}: {e}")
                log_entries.append([nii_path, "", fn, "", json_path, "", f"json-read-error:{e}"])
                continue

            ped = jdata.get("PhaseEncodingDirection") or jdata.get("PhaseEncodingAxis")
            if not ped:
                print(f"Skipping (no PhaseEncodingDirection): {nii_path}")
                log_entries.append([nii_path, "", fn, "", json_path, "", "no-ped"])
                continue

            dir_label = mapping.get(ped)
            if not dir_label:
                print(f"Skipping (no mapping for PhaseEncodingDirection='{ped}'): {nii_path}")
                log_entries.append([nii_path, "", fn, "", json_path, "", "no-mapping"])
                continue

            dir_entity = f"dir-{dir_label}"
            stem = fn[:-7]  # remove .nii.gz
            if "_" in stem:
                head, last = stem.rsplit("_", 1)
                new_stem = f"{head}_{dir_entity}_{last}"
            else:
                new_stem = f"{dir_entity}_{stem}"
            new_fn = new_stem + ".nii.gz"
            new_path = os.path.join(dirpath, new_fn)
            new_json = path_base_json_for_nii(new_path) + ".json"

            print(f"{'DRY:' if args.dry_run else 'DO:'} {nii_path} -> {new_path}  (PED={ped} -> {dir_entity})")

            if args.dry_run:
                log_entries.append([nii_path, new_path, fn, new_fn, json_path, new_json, ped, dir_label, "dry-run"])
                continue

            # safety: skip if target exists
            if os.path.exists(new_path) or os.path.exists(new_json):
                print(f"ERROR: target already exists, skipping: {new_path} or {new_json}")
                log_entries.append([nii_path, new_path, fn, new_fn, json_path, new_json, ped, dir_label, "target-exists"])
                continue

            # perform rename
            try:
                os.rename(nii_path, new_path)
                os.rename(json_path, new_json)
            except Exception as e:
                print(f"ERROR renaming {nii_path} or its JSON: {e}")
                log_entries.append([nii_path, new_path, fn, new_fn, json_path, new_json, ped, dir_label, f"rename-error:{e}"])
                continue

            # update scans TSV files
            total_updated = 0
            for tsv in scans_tsvs:
                changed, count = update_scans_tsv(tsv, fn, new_fn, dry_run=False, backup=not args.no_backup_scans)
                if changed:
                    total_updated += count

            log_entries.append([nii_path, new_path, fn, new_fn, json_path, new_json, ped, dir_label, total_updated])

    # write log CSV
    with open(args.log, 'w', encoding='utf-8', newline='') as lf:
        writer = csv.writer(lf)
        writer.writerow(["old_nii_path", "new_nii_path", "old_basename", "new_basename", "old_json", "new_json", "PED", "dir_label", "scans_tsv_replacements_or_status"])
        for r in log_entries:
            writer.writerow(r)

    print("Done. Log written to", args.log)

if __name__ == "__main__":
    main()