#!/bin/bash
#rename T1w MPRAGE scans with acq-MPRAGE_reg-NORM
# using for site-120 converted before implemented in heudiconv

# BIDSDIR=/Volumes/PsychiatryNeuroinformatics$/Data/Elgan3/ELGAN_BIDS/site-120

# for i in $(cat tmpsubs.txt); do
#     cd $BIDSDIR/${i}/ses-03/anat
#     mv ${i}_ses-03_T1w.nii.gz ${i}_ses-03_acq-MPRAGE_rec-NORM_T1w.nii.gz
#     mv ${i}_ses-03_T1w.json ${i}_ses-03_acq-MPRAGE_rec-NORM_T1w.json
#     done


# Version for site-170 implemented Aug 2026
BIDSDIR=/Volumes/PsychiatryNeuroinformatics$/Data/Elgan3/ELGAN_BIDS/site-170

for i in $(cat tmpsubs.txt); do
    cd $BIDSDIR/${i}/ses-03/anat
    mv ${i}_ses-03_T1w.nii.gz ${i}_ses-03_acq-MPRAGE_T1w.nii.gz
    mv ${i}_ses-03_T1w.json ${i}_ses-03_acq-MPRAGE_T1w.json 
    mv ${i}_ses-03_rec-NORM_T1w.nii.gz ${i}_ses-03_acq-MPRAGE_rec-NORM_T1w.nii.gz
    mv ${i}_ses-03_rec-NORM_T1w.json ${i}_ses-03_acq-MPRAGE_rec-NORM_T1w.json
    done
    