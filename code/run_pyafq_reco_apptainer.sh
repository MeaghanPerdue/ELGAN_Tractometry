#!/bin/bash
#BSUB -n 3				                                     
#BSUB -q long			     
#BSUB -W 24:00
#BSUB -R "span[hosts=1]"
#BSUB -R "rusage[mem=10G]"

# CAUTION! only run this once pyAFQ outputs have been safely copied to local drive
# Run this on afq-waypoints outputs prior to running recobundles segmentation
# clears bundle segmentation outputs from pyAFQ derivatives
# this allows Recobundles segmentation to be performed on the same tractography as AFQ-waypoints

module load apptainer

apptainer exec --containall \
    -B $HOME/elgan_dti/code:/code,$HOME/elgan_dti/data:/bids,$HOME/elgan_dti/data/derivatives:/derivatives,$HOME/elgan_dti/work:/work,$HOME:/home/meaghan.perdue-umw \
    pyafq_latest.sif python /code/afq_run_recobundles.py