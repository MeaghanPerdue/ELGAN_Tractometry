#!/bin/bash
# These MRTrix3 functions were used to remove ADC maps from dwi 4D .nii.gz images that were incorrectly converted by dcm2niix, then correct the bval and bvec files.
# Runs rough tractography for checking accuracy of gradient files, the .tck files should be deleted after visually inspecting in mrview
# After visually inspecting output dwi and .tck files, remove the original converted files and rename the dwi.nii.gz, dwi.bvec, and dwi.bval files according to BIDS

# See data/site-330/README for affected subjects
# run this as ./fix_site330_ADCvols.sh [subject-id]

cd $elgan_dti/data/site-330/${1}/ses-03/dwi

echo "removing first volume ADC image from DWI series"
mrconvert ${1}_ses-03_dwi.nii.gz -coord 3 1:15 dwi.nii.gz 

echo "creating new .bval file to include b=0 as first volume with 15 total volumes"
echo "0 1000 1000 1000 1000 1000 1000 1000 1000 1000 1000 1000 1000 1000 1000" >> dwi.bval

echo "fixing .bval file to include only 15 volumes by removing final column"
awk '{
  for (i = 1; i <= 15 && i <= NF; i++)
    printf "%s%s", $i, (i < 15 && i < NF ? OFS : "")
  printf "\n"
}' ${1}_ses-03_dwi.bvec > dwi.bvec

echo "fix gradients using MRtrix3 dwigradcheck function"
dwigradcheck dwi.nii.gz -fslgrad dwi.bvec dwi.bval -export_grad_fsl dwi_gradcheck.bvec dwi_gradcheck.bval 

echo "create a rough brain mask for gradient check and tractography"
dwi2mask dwi.nii.gz mask.nii.gz -fslgrad dwi_gradcheck.bvec dwi_gradcheck.bval

echo "create rough tractogram for visual inspection"
tckgen -algorithm tensor_det dwi.nii.gz -fslgrad dwi_gradcheck.bvec dwi_gradcheck.bval -mask mask.nii.gz -seed_image mask.nii.gz -select 10k wb_tracts_10k.tck

echo "check output tractogram, rename dwi files and delete extra files" 

