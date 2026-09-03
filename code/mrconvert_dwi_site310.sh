#!/bin/bash
# This script converts Site-310 GE DWI data from DICOMS to BIDS using MRTrix3 mrconvert function
# Running because some subjects did not have informative header info or dicom dir names to use for heudiconv heuristic
# This applied only to subjects NOT containing folder names with 'AX DTI' and those that failed DWI conversion via heudiconv
# also converts multi-echo GRE images using dcm2niix
# Use numeric ID excluding 'sub-E'
# Meaghan Perdue 15 jan 2026

export DICOMS=/Volumes/PsychiatryNeuroinformatics$/Data/Elgan3/Orig_DICOM/Site_310
export BIDS=/Volumes/LaCie/Projects/elgan_dti/data/site-310

for i in $(cat tmpsubs.txt); do
    #mkdir -p $BIDS/sub-E${i}/ses-03/dwi
    #mrconvert $DICOMS/*${i}*/9*/*Series0006/ $BIDS/sub-E${i}/ses-03/dwi/sub-E${i}_ses-03_dwi.nii.gz -json_export $BIDS/sub-E${i}/ses-03/dwi/sub-E${i}_ses-03_dwi.json -export_grad_fsl $BIDS/sub-E${i}/ses-03/dwi/sub-E${i}_ses-03_dwi.bvec $BIDS/sub-E${i}/ses-03/dwi/sub-E${i}_ses-03_dwi.bval
    mv $BIDS/sub-E${i}/ses-03/dwi/sub-E${i}_dwi.nii.gz $BIDS/sub-E${i}/ses-03/dwi/sub-E${i}_ses-03_dwi.nii.gz
    mv $BIDS/sub-E${i}/ses-03/dwi/sub-E${i}_dwi.json $BIDS/sub-E${i}/ses-03/dwi/sub-E${i}_ses-03_dwi.json
    mv $BIDS/sub-E${i}/ses-03/dwi/sub-E${i}_dwi.bvec $BIDS/sub-E${i}/ses-03/dwi/sub-E${i}_ses-03_dwi.bvec
    mv $BIDS/sub-E${i}/ses-03/dwi/sub-E${i}_dwi.bval $BIDS/sub-E${i}/ses-03/dwi/sub-E${i}_ses-03_dwi.bval
    dcm2niix -z y -o $BIDS/sub-E${i}/ses-03/anat -f sub-E${i}_ses-03_echo-%e_MEGRE $DICOMS/*${i}*/9*/*Series0005/
    done