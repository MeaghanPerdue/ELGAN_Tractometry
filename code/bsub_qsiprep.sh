#!/bin/bash 
# loop over job submission for qsiprep on HPC, first creating subject-specific job file, then submit job

for i in $(cat tmpsubs.txt); do
    cat >> bsub_qsiprep_$i.sh << EOF
    #!/bin/bash
    #BSUB -n 4			      
    #BSUB -R "rusage[mem=4G]"                               
    #BSUB -q gpu	
    #BSUB -m V100		     
    #BSUB -W 04:00



    # submit job to run a single participant through qsiprep for DTI only


    module load apptainer

    apptainer run --containall --writable-tmpfs --nv \
        -B $HOME/elgan_dti/code:/code,$HOME/elgan_dti/data:/bids,$HOME/elgan_dti/data/derivatives/qsiprep:/out,$HOME/elgan_dti/work:/work,license.txt:/opt/freesurfer/license.txt \
        qsiprep-v1.0.1.sif \
        /bids /out participant \
        -w /work \
        --fs-license-file /opt/freesurfer/license.txt \
        --skip-bids-validation \
        --participant-label $i \
        --session-id ses-03 \
        --bids-filter-file /code/bids_filter_dti.json \
        --eddy-config /code/eddy_params.json \
        --output-resolution 1.5 \
        --n-cpus 4 \
        --mem 16G \
        --separate-all-dwis \
        --anat-modality T2w \
        --denoise-method none \
        --unringing-method none \
        --use-syn-sdc error \
        --force-syn

    rm -R /home/meaghan.perdue-umw/elgan_dti/work/qsiprep_1_0_wf/sub_${i}
EOF

    bsub bsub_qsiprep_$i.sh
    done


