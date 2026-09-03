#!/bin/bash
# Convert additional ELGAN DICOMS to bids using heudiconv
# 26 Sept 2025

# DO THE FOLLOWING BEFORE RUNNING SCRIPT
# activate dcm2bids environment to use heudiconv conda activate dcm2bids
# update DICOMS path, BIDS path and heudiconv heuristic file (-f option) to the appropriate site
# list ELGAN study IDs to be converted in tmpsubs.txt, excluding leading 'E'
# Some participants have duplicate dicoms within sub-folders, to check, run: 
# ```find . -type d -name "DICOM"```

export DICOMS=/Volumes/PsychiatryNeuroinformatics$/Data/Elgan3/Orig_DICOM/Site_110
export BIDS=/Volumes/LaCie/Projects/elgan_dti/data/site-110

# First run heudiconv 
for i in $(cat tmpsubs.txt); do
    heudiconv -f convertE3_Site110.py \
        -b --minmeta \
        -s E${i} \
        -ss 03 \
        --files $DICOMS/*${i}* \
        -c dcm2niix \
        -o $BIDS \
        --overwrite
    done


echo "Conversion done! Run post-heudiconv-bids-compliance-fix to update PDT2 suffixes"