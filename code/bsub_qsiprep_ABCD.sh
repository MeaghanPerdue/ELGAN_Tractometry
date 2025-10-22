#!/bin/bash 
# loop over job submission for qsiprep on HPC, first creating subject-specific job file, then submit job

for i in $(cat tmpsubs.txt); do
    cat >> bsub_qsiprep_ABCD_$i.sh << EOF
    #!/bin/bash
    #BSUB -n 8				      
    #BSUB -R "rusage[mem=32G]"                               
    #BSUB -q gpu	
    #BSUB -m V100		     
    #BSUB -W 03:00



    # submit job to run a single participant through qsiprep for DTI only


    module load apptainer

    apptainer run --containall --writable-tmpfs --nv \
        -B $HOME/elgan_dti/code:/code,$HOME/elgan_dti/data:/bids,$HOME/elgan_dti/data/derivatives/qsiprep_ABCD:/out,$HOME/elgan_dti/work:/work,license.txt:/opt/freesurfer/license.txt \
        qsiprep-v1.0.1.sif \
        /bids /out participant \
        -w /work \
        --fs-license-file /opt/freesurfer/license.txt \
        --skip-bids-validation \
        --participant-label $i \
        --session-id ses-03 \
        --bids-filter-file /code/bids_filter_ABCD.json \
        --eddy-config /code/eddy_params_ABCD.json \
        --output-resolution 1.25 \
        --n-cpus 8 \
        --mem 32G \
        --anat-modality T1w \
        --denoise-method dwidenoise \
        --unringing-method mrdegibbs 
EOF

    bsub bsub_qsiprep_ABCD_$i.sh
    done


