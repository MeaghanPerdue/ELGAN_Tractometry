#!/bin/bash
# dcm2niix did not output correct bval/bvec files for data from Siemens scanners due to anonymization of the Manufacturer header field
# This runs dwifslgradcheck from mrtrix to correct the gradient files - GRADIENT FILES ARE OVERWRITTEN, copies dumped to .bad_gradient_files
# Run this after heudiconv and post-heudiconv-bids-compliance-fix
# MRtrix3 must be installed for this sript to work

# Set paths to data
export BIDS=/Volumes/LaCie/Projects/elgan_dti/data/site-340

cd $BIDS
mkdir .bad_gradient_files

for i in $(tail -n +2 participants.tsv | cut -f1); do
#for i in $(cat /Volumes/LaCie/Projects/elgan_dti/code/tmpsubs.txt); do
    cp ${i}/ses-03/dwi/${i}_ses-03_dwi.b* .bad_gradient_files
    dwigradcheck -force ${i}/ses-03/dwi/${i}_ses-03_dwi.nii.gz -fslgrad ${i}/ses-03/dwi/${i}_ses-03_dwi.bvec ${i}/ses-03/dwi/${i}_ses-03_dwi.bval -export_grad_fsl ${i}/ses-03/dwi/${i}_ses-03_dwi.bvec ${i}/ses-03/dwi/${i}_ses-03_dwi.bval
    # run on second dwi acquisition if relevant
    #dwigradcheck -force ${i}/ses-03/dwi/${i}_ses-03_acq-vector2_dwi.nii.gz -fslgrad ${i}/ses-03/dwi/${i}_ses-03_acq-vector2_dwi.bvec ${i}/ses-03/dwi/${i}_ses-03_acq-vector2_dwi.bval -export_grad_fsl ${i}/ses-03/dwi/${i}_ses-03_acq-vector2_dwi.bvec ${i}/ses-03/dwi/${i}_ses-03_acq-vector2_dwi.bval
    done 