#!/bin/bash
# These MRTrix3 functions were used to remove ADC maps from dwi 4D .nii.gz images that were incorrectly converted by dcm2niix, then correct the bval and bvec files.
# Runs rough tractography for checking accuracy of gradient files, the .tck files should be deleted after visually inspecting in mrview
# After visually inspecting output dwi and .tck files, remove the original converted files and rename the dwi.nii.gz, dwi.bvec, and dwi.bval files according to BIDS

# See data/site-330/README for affected subjects
# run this as ./fix_site330_ADCvols.sh [subject-id]

cd $elgan_dti/data/site-330

mrconvert ${1}/ses-03/dwi/${1}_ses-03_dwi.nii.gz -coord 3 1:15 ${1}/ses-03/dwi/dwi.nii.gz -fslgrad ${1}/ses-03/dwi/${1}_ses-03_dwi.bvec ${1}/ses-03/dwi/${1}_ses-03_dwi.bval -export_grad_fsl ${1}/ses-03/dwi/dwi.bvec ${1}/ses-03/dwi/dwi.bval --force
dwigradcheck ${1}/ses-03/dwi/dwi.nii.gz -fslgrad ${1}/ses-03/dwi/dwi.bvec ${1}/ses-03/dwi/dwi.bval -export_grad_fsl ${1}/ses-03/dwi/dwi_gradcheck.bvec ${1}/ses-03/dwi/dwi_gradcheck.bval 
dwi2mask ${1}/ses-03/dwi/dwi.nii.gz ${1}/ses-03/dwi/mask.nii.gz
tckgen -algorithm tensor_det ${1}/ses-03/dwi/${1}_ses-03_dwi.nii.gz -fslgrad ${1}/ses-03/dwi/dwi_gradcheck.bvec ${1}/ses-03/dwi/dwi_gradcheck.bval -mask ${1}/ses-03/dwi/mask.nii.gz -seed_image ${1}/ses-03/dwi/mask.nii.gz -select 10k wb_tracts_10k.tck
echo "check output tractogram, rename dwi files and delete extra files" 

