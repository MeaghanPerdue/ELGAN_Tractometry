#!/bin/bash
# copy DWI gradient files from BIDS backup to working bids folder

export BACKUP=/Volumes/PsychiatryNeuroinformatics\$/Data/Elgan3/ELGAN_BIDS/site-220
export WORKING=/Volumes/LaCie/Projects/elgan_dti/data/site-220


for i in $(tail -n +2 $WORKING/participants.tsv | cut -f1); do
    cp -Rfv $BACKUP/${i}/ses-03/dwi/${i}_ses-03_dwi.bvec $WORKING/${i}/ses-03/dwi
    done
    