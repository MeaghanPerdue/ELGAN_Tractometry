#!/usr/bin/env python3
"""Combine AFQ tract profile CSVs across subjects and sessions into a single group CSV."""

import argparse
import pandas as pd
from pathlib import Path

BASE_DIR = Path("/Volumes/LaCie/Projects/elgan_dti/data")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Combine AFQ tract profile CSVs into a single group file."
    )
    parser.add_argument(
        "afq_dir",
        type=str,
        help=(
            "Path to the AFQ derivatives directory, relative to "
            "/Volumes/LaCie/Projects/elgan_dti/data "
            "(e.g. site-150/ELGAN/derivatives/afq)"
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    afq_dir = BASE_DIR / args.afq_dir

    if not afq_dir.exists():
        raise FileNotFoundError(f"AFQ directory not found: {afq_dir}")

    csvs = sorted(
        f for f in afq_dir.glob("sub-*/ses-*/dwi/*_desc-profiles*.csv")
        if not f.name.startswith("._")
    )

    if not csvs:
        raise RuntimeError(f"No AFQ profile CSVs found in: {afq_dir}")

    dfs = []
    for f in csvs:
        # Extract subject and session from path: .../sub-XXXX/ses-YY/dwi/file.csv
        subject = f.parents[2].name.replace("sub-", "")
        session = f.parents[1].name.replace("ses-", "")

        df = pd.read_csv(f)
        df = df.drop(columns=["Unnamed: 0"], errors="ignore")
        df.insert(0, "sessionID", session)
        df.insert(0, "subjectID", subject)
        dfs.append(df)

    group_df = pd.concat(dfs, ignore_index=True)

    out_file = afq_dir / "tract_profiles.csv"
    group_df.to_csv(out_file, index=False)

    print(f"Wrote group tract profiles to: {out_file}")
    print(f"Subjects: {group_df['subjectID'].nunique()}")
    print(f"Sessions: {group_df['sessionID'].nunique()}")
    print(f"Rows: {len(group_df)}")


if __name__ == "__main__":
    main()