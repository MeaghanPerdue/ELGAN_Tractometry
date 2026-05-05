#!/usr/bin/env python3
"""
deduplicate_afq.py
==================
Finds files that are identical across multiple pyAFQ derivatives folders.

Canonical-source rule
---------------------
For any set of identical files the canonical copy is kept in the
*earliest* run folder that contains it.  All later copies are replaced
with relative symlinks pointing back to that canonical file.

This means:
  - If run1 has the file  → run1 is canonical; run2/3/4 symlink to it.
  - If only run2/run3 have the file → run2 is canonical; run3 symlinks to it.
  - Files unique to a single run are never touched.

Cross-run only
--------------
Within-run duplicates (same top-level folder, different sub-paths) are
intentionally ignored.

Usage
-----
    python deduplicate_afq.py [OPTIONS] <folder1> <folder2> ...

    Folders must be supplied in priority order (earliest/canonical first).

    I run this from within the derivatives folder so arguments are easy and report and script are output there.

Options
-------
    --output    Path for the generated shell script  [default: dedup_symlinks.sh]
    --report    Path for the dry-run text report     [default: dedup_report.txt]
    --min-size  Minimum file size in bytes           [default: 1]

Example
-------
    python deduplicate_afq.py \\
        /data/derivatives/afq_run1 \\
        /data/derivatives/afq_run2 \\
        /data/derivatives/afq_run3 \\
        /data/derivatives/afq_run4
"""

import argparse
import hashlib
import os
import sys
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def hash_file(path: Path, chunk: int = 1 << 20) -> str:
    """Return SHA-256 hex digest of a file, read in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def collect_files(root: Path, min_size: int) -> list[Path]:
    """Return all regular (non-symlink) files under *root* >= min_size bytes."""
    files = []
    for dirpath, _dirs, filenames in os.walk(root):
        for fname in filenames:
            p = Path(dirpath) / fname
            if p.is_symlink():          # skip already-linked files
                continue
            try:
                if p.stat().st_size >= min_size:
                    files.append(p)
            except OSError:
                pass
    return files


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def root_of(p: Path, resolved_roots: list[Path]) -> Path | None:
    """Return which top-level resolved root a path belongs to, or None."""
    rp = p.resolve()
    for root in resolved_roots:
        try:
            rp.relative_to(root)
            return root
        except ValueError:
            continue
    return None


def find_duplicates(
    folders: list[Path],
    min_size: int,
) -> tuple[dict[str, Path], list[tuple[Path, Path]]]:
    """
    Walk folders in priority order (earliest first).

    For each unique file content (SHA-256):
      - The first copy encountered becomes the canonical source.
      - Every subsequent copy found in a *different* top-level folder is
        recorded as a duplicate → (duplicate_path, canonical_path).

    Within-folder duplicates are silently skipped.

    Returns
    -------
    canonical_map : hash -> canonical Path
    duplicates    : list of (duplicate_path, canonical_path)
    """
    resolved_roots: list[Path] = [f.resolve() for f in folders]
    canonical_map: dict[str, Path] = {}
    duplicates: list[tuple[Path, Path]] = []

    for folder in folders:
        print(f"  Scanning {folder} ...", flush=True)
        files = collect_files(folder, min_size)
        print(f"    {len(files)} regular files found", flush=True)

        for fpath in files:
            try:
                digest = hash_file(fpath)
            except OSError as exc:
                print(f"    WARNING: cannot read {fpath}: {exc}", file=sys.stderr)
                continue

            if digest not in canonical_map:
                # First time we see this content — register as canonical.
                canonical_map[digest] = fpath
            else:
                canonical = canonical_map[digest]
                # Only record as duplicate when the file lives in a different
                # top-level run folder than the canonical copy.
                if root_of(canonical, resolved_roots) != root_of(fpath, resolved_roots):
                    duplicates.append((fpath, canonical))
                # Same-folder duplicates are silently skipped.

    return canonical_map, duplicates


# ---------------------------------------------------------------------------
# Output generation
# ---------------------------------------------------------------------------

def relative_symlink_target(link_path: Path, target_path: Path) -> str:
    """
    Relative path from link_path's parent directory to target_path.
    Keeps symlinks portable if the whole tree is moved.
    """
    return os.path.relpath(target_path, link_path.parent)


def label_of(p: Path, folders: list[Path]) -> str:
    """Return the name of the top-level run folder that contains *p*."""
    rp = p.resolve()
    for f in folders:
        try:
            rp.relative_to(f.resolve())
            return f.name
        except ValueError:
            continue
    return p.parts[0]  # fallback


def write_shell_script(
    duplicates: list[tuple[Path, Path]],
    output_path: Path,
) -> None:
    """Write a bash script that replaces each duplicate with a relative symlink."""
    lines = [
        "#!/usr/bin/env bash",
        "# Auto-generated by deduplicate_afq.py",
        "# Review carefully before running:",
        "#   bash dedup_symlinks.sh",
        "#",
        "# Each block removes the duplicate and creates a relative symlink",
        "# pointing to the canonical (earliest-run) copy.",
        "#",
        "# set -euo pipefail aborts on any error, preventing partial states.",
        "set -euo pipefail",
        "",
        f"# Total symlink operations: {len(duplicates)}",
        "",
    ]

    by_canonical: dict[Path, list[Path]] = defaultdict(list)
    for dup, canon in duplicates:
        by_canonical[canon].append(dup)

    for canon in sorted(by_canonical):
        dups = by_canonical[canon]
        lines.append(f"# ── canonical: {canon}  ({len(dups)} duplicate(s))")
        for dup in sorted(dups):
            rel = relative_symlink_target(dup, canon)
            lines += [
                f'rm -- "{dup}"',
                f'ln -s "{rel}" "{dup}"',
            ]
        lines.append("")

    output_path.write_text("\n".join(lines))
    output_path.chmod(0o755)


def write_report(
    folders: list[Path],
    duplicates: list[tuple[Path, Path]],
    report_path: Path,
    min_size: int,
) -> None:
    """Write a human-readable dry-run report."""

    total_bytes = 0
    for dup, _ in duplicates:
        try:
            if not dup.is_symlink():
                total_bytes += dup.stat().st_size
        except OSError:
            pass

    # ── Header / summary ─────────────────────────────────────────────────
    lines = [
        "=" * 70,
        "pyAFQ deduplication dry-run report",
        "=" * 70,
        "",
        "Folders scanned (priority / canonical order):",
    ]
    for i, f in enumerate(folders):
        label = "  [primary canonical source]" if i == 0 else ""
        lines.append(f"  {i+1}. {f}{label}")

    lines += [
        "",
        f"Minimum file size           : {min_size} byte(s)",
        f"Duplicate files found       : {len(duplicates)}",
        f"Reclaimable space           : {total_bytes:,} bytes "
        f"({total_bytes / (1024**3):.3f} GiB)",
        "",
    ]

    # ── Breakdown by run pair ─────────────────────────────────────────────
    # e.g.  "afq_run1 → afq_run3 :  412 files,  8.2 GiB"
    run_pair_counts: dict[str, int] = defaultdict(int)
    run_pair_bytes:  dict[str, int] = defaultdict(int)

    for dup, canon in duplicates:
        pair = f"{label_of(canon, folders)} → {label_of(dup, folders)}"
        run_pair_counts[pair] += 1
        try:
            if not dup.is_symlink():
                run_pair_bytes[pair] += dup.stat().st_size
        except OSError:
            pass

    lines += [
        "-" * 70,
        "Duplicates by run pair (canonical → duplicate):",
        "-" * 70,
    ]
    for pair in sorted(run_pair_counts):
        n = run_pair_counts[pair]
        b = run_pair_bytes[pair]
        lines.append(
            f"  {pair:45s}  {n:5d} file(s)   {b / (1024 ** 2):8.1f} MiB"
        )

    # ── Per-file detail ───────────────────────────────────────────────────
    by_canonical: dict[Path, list[Path]] = defaultdict(list)
    for dup, canon in duplicates:
        by_canonical[canon].append(dup)

    lines += [
        "",
        "-" * 70,
        "Detail — files that WOULD be replaced with symlinks:",
        "-" * 70,
        "",
    ]
    for canon in sorted(by_canonical):
        lines.append(f"CANONICAL : {canon}")
        for dup in sorted(by_canonical[canon]):
            try:
                size_mb = (
                    dup.stat().st_size / (1024 ** 2) if not dup.is_symlink() else 0.0
                )
                lines.append(f"  SYMLINK : {dup}  ({size_mb:.2f} MiB)")
            except OSError:
                lines.append(f"  SYMLINK : {dup}  (size unavailable)")
        lines.append("")

    report_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Deduplicate pyAFQ derivatives folders via relative symlinks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "folders",
        nargs="+",
        type=Path,
        help="Run folders in priority order (earliest/canonical first).",
    )
    p.add_argument(
        "--output",
        default="dedup_symlinks.sh",
        type=Path,
        help="Output shell script  [default: dedup_symlinks.sh]",
    )
    p.add_argument(
        "--report",
        default="dedup_report.txt",
        type=Path,
        help="Dry-run report path  [default: dedup_report.txt]",
    )
    p.add_argument(
        "--min-size",
        default=1,
        type=int,
        metavar="BYTES",
        help="Minimum file size in bytes to consider  [default: 1]",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    for f in args.folders:
        if not f.is_dir():
            sys.exit(f"ERROR: '{f}' is not a directory or does not exist.")
    if len(args.folders) < 2:
        sys.exit("ERROR: supply at least two folders to compare.")

    print(f"\nScanning {len(args.folders)} folder(s) in canonical order...")
    _, duplicates = find_duplicates(args.folders, args.min_size)

    total_bytes = sum(
        d.stat().st_size for d, _ in duplicates if not d.is_symlink()
    )

    print(f"\nFound {len(duplicates)} cross-run duplicate file(s).")
    print(
        f"Reclaimable space: {total_bytes:,} bytes "
        f"({total_bytes / (1024**3):.3f} GiB)"
    )

    print(f"\nWriting dry-run report  → {args.report}")
    write_report(args.folders, duplicates, args.report, args.min_size)

    print(f"Writing shell script    → {args.output}")
    write_shell_script(duplicates, args.output)

    print("\nNext steps:")
    print(f"  1. Review the report  :  cat {args.report}")
    print(f"  2. Review the script  :  cat {args.output}")
    print(f"  3. Run when satisfied :  bash {args.output}")
    print()


if __name__ == "__main__":
    main()