#!/bin/bash
# Generates a list of subjects with DWI data in a BIDS dataset


# Set the path to your BIDS dataset
BIDS_DIR="/Volumes/LaCie/Projects/elgan_dti/data/site-120"

# Find all subjects with dwi.nii.gz files
find "$BIDS_DIR" -type f -name "*dwi.nii.gz" | \
    awk -F'/' '{for(i=1;i<=NF;i++){if($i ~ /^sub-/){print $i; break}}}' | 
\
    sort -u

find "$BIDS_DIR" -type f -name "*ses-03_T1w.nii.gz" | \
    awk -F'/' '{for(i=1;i<=NF;i++){if($i ~ /^sub-/){print $i; break}}}' | 
\
    sort -u