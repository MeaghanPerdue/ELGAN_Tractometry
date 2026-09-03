#!/usr/bin/env python3
"""
Created with OpenAI GPT-5-mini via ChanChat
30 Oct 2025
Renaming pyAFQ output files for a subject that had a typo in the file name at input.

rename_pyafq_subject.py

Rename files and directories that include a wrong subject ID (BIDS 'sub-<id>') to a new subject ID.
Designed for pyAFQ outputs in derivatives or BIDS-like directories.

Usage examples:
  # Dry run (no changes):
  python3 rename_pyafq_subject.py /path/to/dataset OLDID NEWID --dry-run

  # Actually perform changes, but don't overwrite existing files:
  python3 rename_pyafq_subject.py /path/to/dataset OLDID NEWID --yes

  # Replace occurrences inside text files too (JSON/TSV/CSV/TXT):
  python3 rename_pyafq_subject.py /path/to/dataset OLDID NEWID --yes --replace-content

Notes:
  - OLDID/NEWID may be given as the bare label (e.g. "01" or "sub-01").
    The script normalizes and focuses on replacing 'sub-OLDID' tokens.
  - Always test with --dry-run first.
"""

import argparse
import csv
import os
import shutil
import sys
from pathlib import Path

TEXT_FILE_EXTS = {'.json', '.tsv', '.csv', '.txt', '.py', '.xml', '.html', '.yaml', '.yml', '.bval', '.bvec', '.tsv.gz'}
# note: .tsv.gz isn't an extension Path.suffix handles, but we'll treat .gz as special if needed.

def normalized_label(label: str) -> str:
    """Return label without 'sub-' prefix if present."""
    if label.startswith('sub-'):
        return label[len('sub-'):]
    return label

def build_replacements(oldlabel: str, newlabel: str):
    """Return tuple of target substrings to replace -> replacement."""
    # Focus on 'sub-OLD' and 'sub_OLD' variants to avoid replacing other occurrences.
    old_sub_dash = f"sub-{oldlabel}"
    old_sub_underscore = f"sub_{oldlabel}"
    new_sub_dash = f"sub-{newlabel}"
    new_sub_underscore = f"sub_{newlabel}"
    return [
        (old_sub_dash, new_sub_dash),
        (old_sub_underscore, new_sub_underscore)
    ]

def is_text_file(path: Path):
    # simple heuristic: extension in TEXT_FILE_EXTS OR small binary check
    ext = ''.join(path.suffixes)  # e.g. for .tsv.gz -> '.tsv.gz'
    if ext in TEXT_FILE_EXTS:
        return True
    # also check common single suffix
    if path.suffix in TEXT_FILE_EXTS:
        return True
    # fallback: read a bit and check for null bytes
    try:
        with path.open('rb') as fh:
            chunk = fh.read(4096)
            if b'\x00' in chunk:
                return False
            return True
    except Exception:
        return False

def replace_in_file(path: Path, replacements, dry_run=False):
    try:
        text = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        # not a utf-8 text file; skip
        return False, "binary-or-non-utf8"
    new_text = text
    changed = False
    for old, new in replacements:
        if old in new_text:
            new_text = new_text.replace(old, new)
            changed = True
    if not changed:
        return False, "no-change"
    if dry_run:
        return True, "would-change"
    # write backup as .bak (optional could be added)
    path.write_text(new_text, encoding='utf-8')
    return True, "changed"

def main():
    p = argparse.ArgumentParser(description="Rename BIDS/pyAFQ files and directories with wrong subject ID.")
    p.add_argument("root", help="Top-level directory of dataset (e.g. path to dataset or derivatives folder).")
    p.add_argument("old_id", help="Old subject label (e.g. '01' or 'sub-01').")
    p.add_argument("new_id", help="New subject label (e.g. '02' or 'sub-02').")
    p.add_argument("--dry-run", action="store_true", help="Don't actually rename; just show what would be done.")
    p.add_argument("--yes", action="store_true", help="Perform changes without asking for interactive confirmation.")
    p.add_argument("--replace-content", action="store_true", help="Also replace occurrences inside text files (json/tsv/csv/txt/etc.).")
    p.add_argument("--overwrite", action="store_true", help="If target path exists, overwrite it (dangerous). By default, skip conflicting renames.")
    p.add_argument("--log-csv", default="rename_pyafq_subject_log.csv", help="CSV file to write rename log to (path).")
    args = p.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.exists():
        print(f"ERROR: Root path does not exist: {root}", file=sys.stderr)
        sys.exit(2)

    oldlabel = normalized_label(args.old_id)
    newlabel = normalized_label(args.new_id)
    if oldlabel == newlabel:
        print("Old and new label are identical after normalization; nothing to do.", file=sys.stderr)
        sys.exit(0)

    replacements = build_replacements(oldlabel, newlabel)

    print("Summary:")
    print(f"  Root: {root}")
    print(f"  Replace tokens (in names): {replacements}")
    print(f"  Replace inside files: {'Yes' if args.replace_content else 'No'}")
    print(f"  Dry run: {'Yes' if args.dry_run else 'No'}")
    print(f"  Overwrite existing: {'Yes' if args.overwrite else 'No'}")
    print()

    if args.dry_run:
        print("DRY RUN mode: no filesystem changes will be made.")
    else:
        if not args.yes:
            resp = input("Proceed with changes? Type 'yes' to continue: ").strip().lower()
            if resp != 'yes':
                print("Aborted by user.")
                sys.exit(0)

    log_rows = []
    # Walk bottom-up to handle directories rename safely
    # Use os.walk with topdown=False
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        current_dir = Path(dirpath)

        # 1) First handle files in this directory
        for fname in filenames:
            src = current_dir / fname
            new_name = fname
            for oldtok, newtok in replacements:
                if oldtok in new_name:
                    new_name = new_name.replace(oldtok, newtok)
            if new_name == fname:
                # no match in filename; maybe need to change inside
                if args.replace_content and is_text_file(src):
                    ok, status = replace_in_file(src, replacements, dry_run=args.dry_run)
                    log_rows.append({
                        'type': 'content' if ok else 'content-skip',
                        'src': str(src),
                        'dst': '',
                        'status': status
                    })
                continue

            dst = current_dir / new_name
            # if destination exists
            if dst.exists():
                if args.overwrite:
                    if not args.dry_run:
                        if dst.is_dir():
                            shutil.rmtree(dst)
                        else:
                            dst.unlink()
                    action = "overwritten"
                else:
                    log_rows.append({
                        'type': 'file-skip',
                        'src': str(src),
                        'dst': str(dst),
                        'status': 'dst-exists-skip'
                    })
                    print(f"SKIP (exists): {src} -> {dst}")
                    continue
            # create parent dir if needed (should exist)
            if args.dry_run:
                print(f"DRY: file rename: {src} -> {dst}")
                log_rows.append({'type': 'file-dry', 'src': str(src), 'dst': str(dst), 'status': 'would-rename'})
            else:
                try:
                    shutil.move(str(src), str(dst))
                    print(f"RENAMED: {src} -> {dst}")
                    log_rows.append({'type': 'file', 'src': str(src), 'dst': str(dst), 'status': 'renamed'})
                except Exception as e:
                    print(f"ERROR renaming file {src} -> {dst}: {e}", file=sys.stderr)
                    log_rows.append({'type': 'file-error', 'src': str(src), 'dst': str(dst), 'status': f'error:{e}'})

            # Optionally replace inside text of the renamed file
            if args.replace_content:
                target_for_content = dst if not args.dry_run else src
                if is_text_file(Path(target_for_content)):
                    ok, status = replace_in_file(Path(target_for_content), replacements, dry_run=args.dry_run)
                    log_rows.append({
                        'type': 'content-after-rename' if ok else 'content-skip',
                        'src': str(target_for_content),
                        'dst': '',
                        'status': status
                    })

        # 2) Then handle directory rename itself
        # current_dir.name might include old token
        dirname = current_dir.name
        new_dirname = dirname
        for oldtok, newtok in replacements:
            if oldtok in new_dirname:
                new_dirname = new_dirname.replace(oldtok, newtok)
        if new_dirname != dirname:
            src_dir = current_dir
            dst_dir = current_dir.with_name(new_dirname)
            if dst_dir.exists():
                if args.overwrite:
                    if args.dry_run:
                        print(f"DRY: would overwrite dir {dst_dir}")
                    else:
                        # remove existing target
                        if dst_dir.is_dir():
                            shutil.rmtree(dst_dir)
                        else:
                            dst_dir.unlink()
                else:
                    print(f"SKIP dir (target exists): {src_dir} -> {dst_dir}")
                    log_rows.append({'type': 'dir-skip', 'src': str(src_dir), 'dst': str(dst_dir), 'status': 'dst-exists-skip'})
                    continue
            if args.dry_run:
                print(f"DRY: dir rename: {src_dir} -> {dst_dir}")
                log_rows.append({'type': 'dir-dry', 'src': str(src_dir), 'dst': str(dst_dir), 'status': 'would-rename'})
            else:
                try:
                    shutil.move(str(src_dir), str(dst_dir))
                    print(f"RENAMED DIR: {src_dir} -> {dst_dir}")
                    log_rows.append({'type': 'dir', 'src': str(src_dir), 'dst': str(dst_dir), 'status': 'renamed'})
                except Exception as e:
                    print(f"ERROR renaming dir {src_dir} -> {dst_dir}: {e}", file=sys.stderr)
                    log_rows.append({'type': 'dir-error', 'src': str(src_dir), 'dst': str(dst_dir), 'status': f'error:{e}'})

    # Optionally: if replace_content was requested, do one final pass for text files that didn't get renamed
    if args.replace_content:
        # second pass to catch files that may not have been renamed but contain tokens
        for pth in root.rglob('*'):
            if pth.is_file():
                try:
                    # check whether we've already logged it to avoid duplicates: skip
                    if is_text_file(pth):
                        ok, status = replace_in_file(pth, replacements, dry_run=args.dry_run)
                        if ok:
                            log_rows.append({'type': 'content-second-pass' if not args.dry_run else 'content-second-dry',
                                             'src': str(pth), 'dst': '', 'status': status})
                except Exception:
                    pass

    # Write log CSV
    logpath = Path(args.log_csv)
    try:
        with logpath.open('w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=['type', 'src', 'dst', 'status'])
            writer.writeheader()
            for row in log_rows:
                writer.writerow(row)
        print(f"Log written to {logpath}")
    except Exception as e:
        print(f"Could not write log to {logpath}: {e}", file=sys.stderr)

    print("Done.")

if __name__ == "__main__":
    main()