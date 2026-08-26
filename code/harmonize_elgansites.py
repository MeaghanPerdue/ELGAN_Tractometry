# Use AFQ-Insight to harmonize ELGAN Tractometry data across sites via NeuroCombat
# Following example here: <https://tractometry.org/AFQ-Insight/auto_examples/plot_hbn_site_profiles.html#sphx-glr-auto-examples-plot-hbn-site-profiles-py>

import pandas as pd
import numpy as np
from scipy import stats

from afqinsight import AFQDataset
from afqinsight.neurocombat_sklearn import CombatModel
from afqinsight.plot import plot_tract_profiles
from collections import OrderedDict

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
# Subplot position layout for pyAFQ waypoint tract names (long-form, as used in ELGAN tractIDs)
# 6x4 grid, left/right mirrored by column, callosal subdivisions each in their own cell
# (no HCC_L/HCC_R since waypoint segmentation only yields Cingulum Cingulate for that pathway)
# --------------------------------------------------------------------------------------------------------

PYAFQ_TO_AFQINSIGHT_POSITIONS = OrderedDict({
    # --- Row 0: Inferior Fronto-occipital / Uncinate ---
    "Left Inferior Fronto-occipital": (0, 0),
    "UNC_L": (0, 1),   # afqinsight translates "Left Uncinate" -> "UNC_L" internally
    "UNC_R": (0, 2),   # afqinsight translates "Right Uncinate" -> "UNC_R" internally
    "Right Inferior Fronto-occipital": (0, 3),

    # --- Row 1: Anterior Thalamic / Corticospinal ---
    "Left Anterior Thalamic": (1, 0),
    "CST_L": (1, 1),   # afqinsight translates "Left Corticospinal" -> "CST_L" internally
    "CST_R": (1, 2),   # afqinsight translates "Right Corticospinal" -> "CST_R" internally
    "Right Anterior Thalamic": (1, 3),

    # --- Row 2: Arcuate / Superior Longitudinal ---
    "ARC_L": (2, 0),   # afqinsight translates "Left Arcuate" -> "ARC_L" internally
    "Left Superior Longitudinal": (2, 1),
    "Right Superior Longitudinal": (2, 2),
    "ARC_R": (2, 3),   # afqinsight translates "Right Arcuate" -> "ARC_R" internally

    # --- Row 3: Inferior Longitudinal / Cingulum Cingulate ---
    "Left Inferior Longitudinal": (3, 0),
    "CGC_L": (3, 1),   # afqinsight translates "Left Cingulum Cingulate" -> "CGC_L" internally
    "CGC_R": (3, 2),   # afqinsight translates "Right Cingulum Cingulate" -> "CGC_R" internally
    "Right Inferior Longitudinal": (3, 3),

    # --- Row 4: Callosal subdivisions, anterior half ---
    "Callosum Orbital": (4, 0),
    "Callosum Anterior Frontal": (4, 1),
    "Callosum Superior Frontal": (4, 2),
    "Callosum Motor": (4, 3),

    # --- Row 5: Callosal subdivisions, posterior half ---
    "Callosum Superior Parietal": (5, 0),
    "Callosum Temporal": (5, 1),
    "Callosum Posterior Parietal": (5, 2),
    "Callosum Occipital": (5, 3),
})

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
#plt.show()

# --------------------------------------------------------------------------------------------------------
# Plot mean bundle profiles by site before harmonization
# explicitly indicate nrows and ncols else index error
# --------------------------------------------------------------------------------------------------------

site_figs = plot_tract_profiles(
    X=afqdata,
    group_by=afqdata.y[:, 0],
    group_by_name="Site",
    figsize=(14, 14),
    subplot_positions=PYAFQ_TO_AFQINSIGHT_POSITIONS,
    nrows=6,
    ncols=4
)

#plt.show()

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

harmonized.to_csv('/Volumes/LaCie/Projects/elgan_dti/data/harmonize/elgan_afq_prob_harmonized.csv', index = False)

# --------------------------------------------------------------------------------------------------------
# Plot harmonized data
# --------------------------------------------------------------------------------------------------------

site_figs_harmonized = plot_tract_profiles(
    X=harmonized,
    group_by=merged_labels,
    group_by_name="Site",
    figsize=(14, 14),
    subplot_positions=PYAFQ_TO_AFQINSIGHT_POSITIONS,
    nrows=6,
    ncols=4
)

plt.show()

for name, fig in site_figs_harmonized.items():
    fig.savefig(
        f"/Volumes/LaCie/Projects/elgan_dti/data/harmonize/harmonized_{name}_tract_profiles.png",
        dpi=300,
        bbox_inches="tight"
    )