import pandas as pd
from pathlib import Path

afq_dir = Path("/Volumes/LaCie/Projects/elgan_dti/data/site-330/derivatives/afq")

csvs = sorted(
    afq_dir.glob("sub-*/ses-03/dwi/*_desc-profiles_tractography.csv")
)

# If sessionless, use:
# csvs = afq_dir.glob("sub-*/dwi/*_desc-profiles_tractography.csv")

if not csvs:
    raise RuntimeError("No AFQ profile CSVs found")

dfs = [pd.read_csv(f) for f in csvs]

group_df = pd.concat(dfs, ignore_index=True)

group_df.to_csv(afq_dir / "tract_profiles.csv", index=False)

print(f"Wrote {afq_dir / 'tract_profiles.csv'}")