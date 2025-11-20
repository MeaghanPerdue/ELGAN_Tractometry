# This script removes all outputs from bundle recognition on and re-runs with recobundles
# use this in order to run Recobundles segmentation on the same tractography used for AFQ-waypoints

from AFQ.api.group import GroupAFQ

# Initialize AFQ object
afq = GroupAFQ(
    bids_path="/bids",
    output_dir="/derivatives/afq",
    seg_algo="reco",                # switch to RecoBundles
    refine_reco=True,               # enable refinement
    rb_recognize_params={
        "model_clust_thr": 1.25,
        "pruning_thr": 12,
        "reduction_thr": 25
    }
)

# Remove old segmentation outputs only
afq.clobber(dependent_on="recog")

# Recompute segmentation and subsequent steps
afq.export_all()
