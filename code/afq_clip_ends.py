# This script removes all outputs from bundle recognition on and re-runs segmentation and tract profiling with end-clipping ON
# use this in order to do end-clipping using existing tractography
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
    segmentation_params= dict(
        clip_edges = True
    )
)

# Remove old segmentation outputs only
afq.cmd_outputs(dependent_on="recog")

# Recompute segmentation and subsequent steps
afq.export_all()
