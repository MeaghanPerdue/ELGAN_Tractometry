# This script removes all outputs from bundle recognition on and re-runs with recobundles
# use this in order to run Recobundles segmentation on the same tractography used for AFQ-waypoints 

from AFQ.api.group import GroupAFQ
import AFQ.api.bundle_dict as abd

# Initialize AFQ object

afq = GroupAFQ(
    bids_path="/bids",
    preproc_pipeline='qsiprep',
    participant_labels = "['E2200321H']"
    output_dir="/derivatives/afq_test",
    tracking_params=dict(
        directions='det',
        odf_model='DTI'
    )
)


# Remove old segmentation outputs only
afq.clobber()


# Recompute segmentation and subsequent steps
afq.export_all()
