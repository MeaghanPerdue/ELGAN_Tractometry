#!/bin/bash
# Convert site-310 DWI DICOMs using dcm2niix
# for subjects who failed conversion via heudiconv because dicom files were named with very little information
# run as ./dcm2niix_site310_dwi.sh 3100041K _Series0006
# run this for a batch of subjects with run_dcm2niix_site310_dwi.sh

export DICOMDIR=/Volumes/PsychiatryNeuroinformatics\$/Data/Elgan3/Orig_DICOM/Site_310
export BIDSDIR=/Volumes/LaCie/Projects/elgan_dti/data/site-310

dcm2niix -z y \
    -o $BIDSDIR/sub-E${1}/ses-03/dwi \
    -f sub-E${1}_ses-03_dwi \
    $DICOMDIR/*${1}*/9_Other\ scans/${2}

cp $BIDSDIR/dwi.bval $BIDSDIR/sub-E${1}/ses-03/dwi/sub-E${1}_ses-03_dwi.bval
cp $BIDSDIR/dwi.bvec $BIDSDIR/sub-E${1}/ses-03/dwi/sub-E${1}_ses-03_dwi.bvec