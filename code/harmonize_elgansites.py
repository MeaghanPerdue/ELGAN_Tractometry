# Use AFQ-Insight to harmonize ELGAN Tractometry data across sites via NeuroCombat
# Following example here: <https://tractometry.org/AFQ-Insight/auto_examples/plot_hbn_site_profiles.html#sphx-glr-auto-examples-plot-hbn-site-profiles-py>

import pandas as pd
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split

from afqinsight import AFQDataset
from afqinsight.neurocombat_sklearn import CombatModel
from afqinsight.plot import plot_tract_profiles

# --------------------------------------------------------------------------------------------------------
# First, organize the aggregated pyAFQ profiles data from all sites according to AFQ-Browser data format
# This requires separate .csv files for nodes (tract profiles) and subjects (participant info)
# We will take as input the motion-filtered dataset that was used for Tractable in R:
# --------------------------------------------------------------------------------------------------------

nodes = pd.read_csv(
        '/Volumes/LaCie/Projects/elgan_dti/data/ELGAN_afq_prob_filtered.csv', 
        usecols =['subjectID', 'tractID', 'nodeID', 'dti_fa', 'dti_md']
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
# Plot mean bundle profiles by site
# --------------------------------------------------------------------------------------------------------




