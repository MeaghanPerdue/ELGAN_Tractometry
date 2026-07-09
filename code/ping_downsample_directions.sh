#!/bin/bash
# Downsample number of directions in PING data to match ELGAN (32 downsample to 16)

PING_BIDS="/Volumes/LaCie/Projects/elgan_dti/data/PING"

#select B0 plus 15 directions from full DTI acquisition, every other volume
for i in tmpsubs.txt; do
    cd $PING_BIDS/${i}/ses-01/dwi
    mrconvert ${i}_ses-01_dwi.nii.gz ${i}_ses-01_rec-16dir_dwi.nii.gz \
        -fslgrad ${i}_ses-01_dwi.bvec ${i}_ses-01_dwi.bval \
        -json_import ${i}_ses-01_dwi.json \
        -coord 3 0:2:end \
        -export_grad_fsl ${i}_ses-01_rec-16dir_dwi.bvec ${i}_ses-01_rec-16dir_dwi.bval \
        -json_export ${i}_ses-01_rec-16dir_dwi.json
    done
