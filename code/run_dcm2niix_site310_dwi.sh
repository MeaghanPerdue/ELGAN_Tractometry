#!/bin/bash
# Run batch of subjects through dcm2niix conversion for DWI data
# list subject IDs and DWI dicoms folder names as separate columns in site310_dwi_subs.txt

sublist="site310_dwi_subs.txt"

while read sub; do
    sh dcm2niix_site310_dwi.sh ${sub}
    done < "$sublist"