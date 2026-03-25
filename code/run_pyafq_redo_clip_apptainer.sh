#!/bin/bash
#BSUB -n 3				                                     
#BSUB -q short			     
#BSUB -W 06:00
#BSUB -R "span[hosts=1]"
#BSUB -R "rusage[mem=10G]"

# CAUTION! only run this once pyAFQ outputs have been safely copied to local drive
# Rerun pyafq bundle segmentation only
# clears bundle segmentation outputs from pyAFQ derivatives


module load apptainer

apptainer exec --containall --cleanenv \
    -B $HOME/elgan_dti/code:/code,$HOME/elgan_dti/data:/bids,$HOME/elgan_dti/data/derivatives:/derivatives,$HOME/elgan_dti/work:/work,$HOME:/home/meaghan.perdue-umw \
    pyafq_latest.sif python /code/afq_clip_ends.py