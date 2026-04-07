# This script removes all outputs from tractography on and re-runs with deterministic tractography

import os
import os.path as op
from AFQ.api.group import GroupAFQ
import AFQ.api.bundle_dict as abd
import bids
from bids.layout import BIDSLayout


# Initialize AFQ object

afq = GroupAFQ(
    bids_path="/bids",
    preproc_pipeline='qsiprep',
    output_dir="/derivatives/afq",
    tracking_params=dict(
        directions="det"
    ), 
    segmentation_params= dict(
        clip_edges = False
    )
)

# Remove old segmentation outputs only
afq.cmd_outputs(dependent_on="track")

# Recompute segmentation and subsequent steps
afq.export_all()
