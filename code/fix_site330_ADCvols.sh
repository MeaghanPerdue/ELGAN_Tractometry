#!/bin/bash
# These MRTrix3 functions were used to remove ADC maps from dwi 4D .nii.gz images that were incorrectly converted by dcm2niix, then correct the bval and bvec files.
# Runs rough tractography for checking accuracy of gradient files, the .tck files should be deleted after visually inspecting in mrview
# After visually inspecting output dwi and .tck files, remove the original converted files and rename the dwi.nii.gz, dwi.bvec, and dwi.bval files according to BIDS

# See data/site-330/README for affected subjects
# run this as ./fix_site330_ADCvols.sh [subject-id]

cd $elgan_dti/data/site-330/${1}/ses-03/dwi

mrconvert ${1}_ses-03_dwi.nii.gz -coord 3 1:15 dwi.nii.gz -fslgrad ${1}_ses-03_dwi.bvec ${1}_ses-03_dwi.bval -export_grad_fsl dwi.bvec dwi.bval --force
dwigradcheck dwi.nii.gz -fslgrad dwi.bvec dwi.bval -export_grad_fsl dwi_gradcheck.bvec dwi_gradcheck.bval 
dwi2mask dwi.nii.gz mask.nii.gz
tckgen -algorithm tensor_det ${1}_ses-03_dwi.nii.gz -fslgrad dwi_gradcheck.bvec dwi_gradcheck.bval -mask mask.nii.gz -seed_image mask.nii.gz -select 10k wb_tracts_10k.tck
echo "check output tractogram, rename dwi files and delete extra files" 

