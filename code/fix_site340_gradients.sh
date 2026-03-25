#!/bin/bash
# These MRTrix3 functions were used to remove ADC maps from dwi 4D .nii.gz images that were incorrectly converted by dcm2niix, then correct the bval and bvec files.
# Runs rough tractography for checking accuracy of gradient files, the .tck files should be deleted after visually inspecting in mrview
# After visually inspecting output dwi and .tck files, remove the original converted files and rename the dwi.nii.gz, dwi.bvec, and dwi.bval files according to BIDS
# to visually inspect mask and tractogram in mrtrix, navigate to subject's dwi folder and run:
# mrview mask.nii.gz --tractography.load wb_tracts_10k.tck
# imperfect mask ok/expected due to lack of preprocessing, as long as major streamlines seem good

# See data/site-330/README for affected subjects
# run this as ./fix_site340_ADCvols.sh [subject-id]

cd $elgan_dti/data/site-340/${1}/ses-03/dwi


echo "fix gradients using MRtrix3 dwigradcheck function"
dwigradcheck ${1}_ses-03_dwi.nii.gz -fslgrad ${1}_ses-03_dwi.bvec ${1}_ses-03_dwi.bval -export_grad_fsl dwi_gradcheck.bvec dwi_gradcheck.bval 

echo "create a rough brain mask for gradient check and tractography"
dwi2mask ${1}_ses-03_dwi.nii.gz mask.nii.gz -fslgrad dwi_gradcheck.bvec dwi_gradcheck.bval

echo "create rough tractogram for visual inspection"
tckgen -algorithm tensor_det ${1}_ses-03_dwi.nii.gz -fslgrad dwi_gradcheck.bvec dwi_gradcheck.bval -mask mask.nii.gz -seed_image mask.nii.gz -select 10k wb_tracts_10k.tck

echo "check output tractogram, rename dwi files and delete extra files" 
mrview mask.nii.gz --tractography.load wb_tracts_10k.tck

### Make sure the tracts look good before running these!
#dwi.nii.gz ${1}_ses-03_dwi.nii.gz
#dwi_gradcheck.bvec ${1}_ses-03_dwi.bvec
#dwi_gradcheck.bval ${1}_ses-03_dwi.bval
#rm mask.nii.gz
#rm wb_tracts_10k.tck
#rm dwi*