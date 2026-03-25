# This script removes all outputs from bundle recognition on and re-runs segmentation and tract profiling with end-clipping ON
# use this in order to do end-clipping using existing tractography

from AFQ.api.group import GroupAFQ
import AFQ.api.bundle_dict as abd

# Initialize AFQ object

afq = GroupAFQ(
    bids_path="/bids",
    output_dir="/derivatives/afq",
    segmentation_params= dict(
        clip_edges = True
    )
)


# Remove old segmentation outputs only
afq.clobber(dependent_on="recog")


# Recompute segmentation and subsequent steps
afq.export_all()
