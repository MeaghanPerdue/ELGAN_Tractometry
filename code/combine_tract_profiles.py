import pandas as pd
from pathlib import Path

afq_dir = Path("/Volumes/LaCie/Projects/elgan_dti/data/site-330/derivatives/afq")

csvs = sorted(
    f for f in afq_dir.glob("sub-*/ses-*/dwi/*_desc-profiles*.csv")
    if not f.name.startswith("._")
)

if not csvs:
    raise RuntimeError("No AFQ profile CSVs found")

dfs = []


for f in csvs:
    # Extract subject and session from the path
    # .../sub-XXXX/ses-YY/dwi/file.csv
    subject = f.parents[2].name.replace("sub-", "")
    session = f.parents[1].name.replace("ses-", "")

    # Read CSV
    df = pd.read_csv(f)

    # Drop unwanted index column if present
    df = df.drop(columns=["Unnamed: 0"], errors="ignore")

    # Insert subjectID and sessionID columns at the front
    df.insert(0, "sessionID", session)
    df.insert(0, "subjectID", subject)

    dfs.append(df)


# Concatenate all subjects/sessions
group_df = pd.concat(dfs, ignore_index=True)

out_file = afq_dir / "tract_profiles.csv"
group_df.to_csv(out_file, index=False)

print(f"Wrote group tract profiles to: {out_file}")
print(f"Subjects: {group_df['subjectID'].nunique()}")
print(f"Sessions: {group_df['sessionID'].nunique()}")
print(f"Rows: {len(group_df)}")