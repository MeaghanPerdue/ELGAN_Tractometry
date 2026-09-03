#!/bin/bash
#BSUB -n 16				      
#BSUB -R "rusage[mem=16G]"                               
#BSUB -q long			     
#BSUB -W 24:00


# run pyafq on bids dataset
# set appropriate config file
# TEMPLATEFLOW_HOME directory and environment variable must be set for recobundles

module load apptainer

export TEMPLATEFLOW_HOME=$HOME/templateflow

apptainer run --containall \
    -B $HOME/elgan_dti/code:/code,$HOME/elgan_dti/data:/bids,$HOME/elgan_dti/data/derivatives:/derivatives,$HOME/elgan_dti/work:/work,$HOME:/home/meaghan.perdue-umw, \
    pyafq_latest.sif /code/config_afq_siemens.toml
