#!/bin/bash
# Convert additional ELGAN DICOMS to bids using heudiconv
# 26 Sept 2025

# activate dcm2bids environment to use heudiconv conda activate dcm2bids

export DICOMS=/Volumes/PsychiatryNeuroinformatics$/Data/Elgan3/Orig_DICOM/Site_150
export BIDS=/Volumes/LaCie/Projects/elgan_dti/data

# First run heudiconv 
for i in $(cat tmpsubs.txt); do
    heudiconv -f convertE3_Site150.py \
        -b --minmeta \
        -s E${i} \
        -ss 03 \
        --files $DICOMS/*${i}* \
        -c dcm2niix \
        -o $BIDS \
        --overwrite
    done

# Next fix the DTI series by concatenating the B0 volume with the DTI series
# this didn't quite work, depends on file naming and folder structure of input DICOMS
# for i in $(cat tmpsubs.txt); do
#     dcm2niix -z y -o $BIDS/sub-E${i}/ses-03/dwi -f B0 $DICOMS/*${i}*/9_Other*/WIP\ DTI_medium_iso_401001/
#     cd $BIDS/sub-E${i}/ses-03/dwi
#     fslmerge -t merged.nii.gz B0.nii.gz sub-E${i}_ses-03_dwi.nii.gz
#     echo "$(tr -d '\n' < B0.bval) $(tr -d '\n' < sub-E${i}_ses-03_dwi.bval)" > merged.bval
#     paste -d ' ' B0.bvec sub-E${i}_ses-03_dwi.bvec > merged.bvec
#     mv merged.nii.gz sub-E${i}_ses-03_dwi.nii.gz
#     mv merged.bval sub-E${i}_ses-03_dwi.bval
#     mv merged.bvec sub-E${i}_ses-03_dwi.bvec
#     echo "run fix_bids_json_elgan3_dwi.py to insert json metadata"
#     done
