#!/bin/bash
#BSUB -n 1				      
#BSUB -R "rusage[mem=16G]"                                
#BSUB -q short			     
#BSUB -W 02:00
#BSUB -o "$HOME/%J.out"

module load apptainer

apptainer build qsiprep-v1.0.1.sif docker://pennlinc/qsiprep:1.0.1

