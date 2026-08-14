# Use AFQ-Insight to harmonize ELGAN Tractometry data across sites via NeuroCombat
# Following example here: <https://tractometry.org/AFQ-Insight/auto_examples/plot_hbn_site_profiles.html#sphx-glr-auto-examples-plot-hbn-site-profiles-py>

import pandas as pd
import numpy as np
from scipy import stats

from afqinsight import AFQDataset
from afqinsight.neurocombat_sklearn import CombatModel
from afqinsight.plot import plot_tract_profiles
from afqinsight.plot import POSITIONS

import matplotlib.pyplot as plt
import seaborn as sns

# --------------------------------------------------------------------------------------------------------
# First, organize the aggregated pyAFQ profiles data from all sites according to AFQ-Browser data format
# This requires separate .csv files for nodes (tract profiles) and subjects (participant info)
# We will take as input the motion-filtered dataset that was used for Tractable in R:
# --------------------------------------------------------------------------------------------------------

nodes = (
    pd.read_csv(
        '/Volumes/LaCie/Projects/elgan_dti/data/ELGAN_afq_prob_filtered.csv',
        usecols=['subjectID', 'tractID', 'nodeID', 'dti_fa', 'dti_md']
    )
    .query(
        "tractID not in ['Left Posterior Arcuate', "
        "'Right Posterior Arcuate', "
        "'Left Vertical Occipital', "
        "'Right Vertical Occipital']"
    )
)
        
nodes.to_csv('/Volumes/LaCie/Projects/elgan_dti/data/harmonize/nodes.csv', index = False)

subjects = (
    pd.read_csv(
        '/Volumes/LaCie/Projects/elgan_dti/data/ELGAN_afq_prob_filtered.csv', 
        usecols =['subjectID', 'site', 'vendor', 'female', 'mri_age', 'gadays', 'bw', 'iq85', 'mean_fd', 'CNR0_mean', 'CNR1_mean']
        )
        .drop_duplicates()
        .reset_index(drop=True)
)

subjects.to_csv('/Volumes/LaCie/Projects/elgan_dti/data/harmonize/subjects.csv', index = False)

# --------------------------------------------------------------------------------------------------------
# Read in the AFQ-Browser-formatted data
# --------------------------------------------------------------------------------------------------------

afqdata = AFQDataset.from_files(
    fn_nodes="/Volumes/LaCie/Projects/elgan_dti/data/harmonize/nodes.csv",
    fn_subjects="/Volumes/LaCie/Projects/elgan_dti/data/harmonize/subjects.csv",
    dwi_metrics=["dti_md", "dti_fa"],
    target_cols=['site', 'vendor', 'female', 'mri_age', 'gadays', 'bw', 'iq85', 'mean_fd', 'CNR0_mean', 'CNR1_mean']
    )



# --------------------------------------------------------------------------------------------------------
# update positions dictionary with aliases from pyAFQ and fix subplot array
# --------------------------------------------------------------------------------------------------------

my_positions = POSITIONS.copy()

my_positions.update({
    "Left Arcuate": POSITIONS["ARC_L"],
    "Right Arcuate": POSITIONS["ARC_R"],
    "Left Anterior Thalamic": POSITIONS["ATR_L"],
    "Right Anterior Thalamic": POSITIONS["ATR_R"],
    "Left Cingulum Cingulate": POSITIONS["CGC_L"],
    "Right Cingulum Cingulate": POSITIONS["CGC_R"],
    "Left Corticospinal": POSITIONS["CST_L"],
    "Right Corticospinal": POSITIONS["CST_R"],
    "Left Inferior Fronto-occipital": POSITIONS["IFOF_L"],
    "Right Inferior Fronto-occipital": POSITIONS["IFOF_R"],
    "Left Inferior Longitudinal": POSITIONS["ILF_L"],
    "Right Inferior Longitudinal": POSITIONS["ILF_R"],
    "Left Superior Longitudinal": POSITIONS["SLF_L"],
    "Right Superior Longitudinal": POSITIONS["SLF_R"],
    "Left Uncinate": POSITIONS["UNC_L"],
    "Right Uncinate": POSITIONS["UNC_R"],
    "Callosum Anterior Frontal": POSITIONS["AntFrontal"],
    "Callosum Motor": POSITIONS["Motor"],
    "Callosum Occipital": POSITIONS["Occipital"],
    "Callosum Orbital": POSITIONS["Orbital"],
    "Callosum Posterior Parietal": POSITIONS["PostParietal"],
    "Callosum Superior Frontal": POSITIONS["SupFrontal"],
    "Callosum Superior Parietal": POSITIONS["SupParietal"],
    "Callosum Temporal": POSITIONS["Temporal"]
})

my_positions["Callosum Superior Parietal"] = (4, 0)
my_positions["Callosum Temporal"] = (4, 1)
my_positions["Callosum Posterior Parietal"] = (4, 2)
my_positions["Callosum Occipital"] = (4, 3)

my_positions["SupParietal"] = (4, 0)
my_positions["Temporal"] = (4, 1)
my_positions["PostParietal"] = (4, 2)
my_positions["Occipital"] = (4, 3)

# Save this for future use
PYAFQ_TO_AFQINSIGHT_POSITIONS = my_positions

# --------------------------------------------------------------------------------------------------------
# Check distribution of subjects across sites before harmonizing 
# merge small Ns (<10) if similar scan parameters
# --------------------------------------------------------------------------------------------------------

site_idx = afqdata.target_cols.index("site")
site_labels = afqdata.y[:, site_idx]
print(pd.Series(site_labels).value_counts())

# Merge site-140 and site-170 (matching scanner vendor + DTI protocol)
merged_labels = np.where(
    np.isin(site_labels, ["site-140", "site-170"]),
    "site-140_170_merged",
    site_labels,
)
afqdata.y[:, site_idx] = merged_labels

# Keep string labels for plotting, and build a numeric encoding for ComBat
site_codes, site_uniques = pd.factorize(merged_labels)
print(pd.Series(merged_labels).value_counts())


# --------------------------------------------------------------------------------------------------------
# Check correlation of covariates and covariate differences by site
# --------------------------------------------------------------------------------------------------------

# --- 1. Pairwise correlation: gadays vs bw ---
ga_idx = afqdata.target_cols.index("gadays")
bw_idx = afqdata.target_cols.index("bw")

ga = afqdata.y[:, ga_idx].astype(float)
bw = afqdata.y[:, bw_idx].astype(float)

# drop any pairs with NaN in either variable
mask = ~np.isnan(ga) & ~np.isnan(bw)

r, p = stats.pearsonr(ga[mask], bw[mask])
print(f"Pearson r (gadays vs bw): r={r:.3f}, p={p:.4g}, n={mask.sum()}")

rho, p_s = stats.spearmanr(ga[mask], bw[mask])
print(f"Spearman rho (gadays vs bw): rho={rho:.3f}, p={p_s:.4g}")

# ga_day and bw correlate strongly, use only ga_days in harmonization

# --- 2. Do gadays, bw, iq85, mri_age differ significantly by site? ---
vars_to_check = ["gadays", "bw", "iq85", "mri_age"]

# use merged_labels (post-merge site groupings) as the grouping variable
df = pd.DataFrame({
    "site": merged_labels,
    **{v: afqdata.y[:, afqdata.target_cols.index(v)].astype(float) for v in vars_to_check}
})

for v in vars_to_check:
    sub = df[["site", v]].dropna()
    groups = [sub.loc[sub["site"] == s, v].values for s in sub["site"].unique()]
    # drop groups that are empty after dropna
    groups = [g for g in groups if len(g) > 0]

    # Kruskal-Wallis is safer than one-way ANOVA here given small/uneven
    # site sizes and no guarantee of normality within site
    h_stat, p_kw = stats.kruskal(*groups)
    print(f"{v}: Kruskal-Wallis H={h_stat:.3f}, p={p_kw:.4g}, n={len(sub)}, "
          f"n_sites={sub['site'].nunique()}")

## mri_age differs significantly by site -- follow up
mri_age_summary = df.groupby("site")["mri_age"].agg(
    n="count", median="median", mean="mean", std="std", min="min", max="max"
).sort_values("median")
print(mri_age_summary)

# order sites by median mri_age for readability
order = df.groupby("site")["mri_age"].median().sort_values().index

fig, ax = plt.subplots(figsize=(10, 6))
sns.boxplot(data=df, x="site", y="mri_age", order=order, showfliers=False,
            color="lightgray", ax=ax)
sns.stripplot(data=df, x="site", y="mri_age", order=order,
              color="black", alpha=0.6, jitter=0.15, ax=ax)

# annotate n per site on the x-axis labels
n_per_site = df.groupby("site")["mri_age"].count()
ax.set_xticklabels([f"{s}\n(n={n_per_site[s]})" for s in order], rotation=45, ha="right")
ax.set_ylabel("MRI age")
ax.set_xlabel("")
ax.set_title("MRI age by site (Kruskal-Wallis p=0.0028)")
plt.tight_layout()
plt.show()

# --------------------------------------------------------------------------------------------------------
# Plot mean bundle profiles by site before harmonization
# --------------------------------------------------------------------------------------------------------

site_figs = plot_tract_profiles(
    X=afqdata,
    group_by=afqdata.y[:, 0],
    group_by_name="Site",
    figsize=(14, 14),
    subplot_positions=PYAFQ_TO_AFQINSIGHT_POSITIONS
)

plt.show()

for name, fig in site_figs.items():
    fig.savefig(
        f"/Volumes/LaCie/Projects/elgan_dti/data/harmonize/unharmonized_{name}_tract_profiles.png",
        dpi=300,
        bbox_inches="tight"
    )


# --------------------------------------------------------------------------------------------------------
# Harmonize data across sites via neuroComBat
# --------------------------------------------------------------------------------------------------------

age_idx = afqdata.target_cols.index("mri_age")
sex_idx = afqdata.target_cols.index("female")
ga_idx = afqdata.target_cols.index("gadays")

continuous_covariates = np.column_stack([
    afqdata.y[:, age_idx].astype(float),
    afqdata.y[:, ga_idx].astype(float),
])

discrete_covariates = afqdata.y[:, sex_idx][:, np.newaxis].astype(float)

combat = CombatModel()
combat.fit(
    afqdata.X,
    site_codes[:, np.newaxis],
    discrete_covariates,
    continuous_covariates,
)



harmonized = afqdata.copy()
harmonized.X = combat.transform(
    afqdata.X,
    site_codes[:, np.newaxis],
    discrete_covariates,
    continuous_covariates,
)
# --------------------------------------------------------------------------------------------------------
# Plot harmonized data
# --------------------------------------------------------------------------------------------------------

site_figs_harmonized = plot_tract_profiles(
    X=harmonized,
    group_by=merged_labels,
    group_by_name="Site",
    figsize=(14, 14),
    subplot_positions=PYAFQ_TO_AFQINSIGHT_POSITIONS
)

plt.show()

for name, fig in site_figs_harmonized.items():
    fig.savefig(
        f"/Volumes/LaCie/Projects/elgan_dti/data/harmonize/harmonized_{name}_tract_profiles.png",
        dpi=300,
        bbox_inches="tight"
    )