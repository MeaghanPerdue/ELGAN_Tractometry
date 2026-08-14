# Use AFQ-Insight to harmonize ELGAN Tractometry data across sites via NeuroCombat
# Following example here: <https://tractometry.org/AFQ-Insight/auto_examples/plot_hbn_site_profiles.html#sphx-glr-auto-examples-plot-hbn-site-profiles-py>

import pandas as pd
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split

from afqinsight import AFQDataset
from afqinsight.neurocombat_sklearn import CombatModel
from afqinsight.plot import plot_tract_profiles
from afqinsight.plot import POSITIONS

import matplotlib.pyplot as plt

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
# Plot mean bundle profiles by site
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