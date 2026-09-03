
#!/usr/bin/env python3
import argparse
from pathlib import Path

def main():
    ap = argparse.ArgumentParser(description="Fix stray .nii.json sidecars to .json")
    ap.add_argument("bids_dir", type=Path, help="Path to BIDS dataset root")
    ap.add_argument("--apply", action="store_true", help="Actually perform renames (default is dry-run)")
    args = ap.parse_args()

    n_found = n_fixed = n_skipped = 0

    for json_path in args.bids_dir.rglob("*.nii.json"):
        n_found += 1
        # Turn ...foo.nii.json → ...foo.json
        target = Path(str(json_path).replace(".nii.json", ".json"))
        # Also check that the matching NIfTI exists (...foo.nii.gz or ...foo.nii)
        nii_gz = Path(str(target).replace(".json", ".nii.gz"))
        nii = Path(str(target).replace(".json", ".nii"))

        if target.exists():
            print(f"[SKIP] Target already exists: {target}")
            n_skipped += 1
            continue

        if not (nii_gz.exists() or nii.exists()):
            print(f"[WARN] No matching NIfTI found for {json_path} "
                  f"(expected {nii_gz.name} or {nii.name}). Renaming JSON anyway.")
        print(f"[RENAME]{' (dry-run)' if not args.apply else ''}: {json_path} → {target}")

        if args.apply:
            json_path.rename(target)
            n_fixed += 1

    print(f"\nFound: {n_found}, Fixed: {n_fixed}, Skipped: {n_skipped}")
    if not args.apply:
        print("Dry-run complete. Re-run with --apply to make changes.")

if __name__ == "__main__":
    main()
