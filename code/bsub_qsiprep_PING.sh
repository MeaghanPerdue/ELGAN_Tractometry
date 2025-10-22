#!/bin/bash 
# loop over job submission for qsiprep on HPC, first creating subject-specific job file, then submit job

for i in $(cat tmpsubs.txt); do
    cat >> bsub_qsiprep_$i.sh << EOF
    #!/bin/bash
    #BSUB -n 8				      
    #BSUB -R "rusage[mem=16G]"                               
    #BSUB -q gpu	
    #BSUB -m V100		     
    #BSUB -W 04:00


    # submit job to run a single participant through qsiprep for DTI only


    module load apptainer

    apptainer run --containall --writable-tmpfs --nv -B /home/meaghan.perdue-umw/elgan_dti/code:/code,/home/meaghan.perdue-umw/elgan_dti/data:/bids,/home/meaghan.perdue-umw/elgan_dti/data/derivatives/qsiprep:/out,/home/meaghan.perdue-umw/elgan_dti/work:/work,license.txt:/opt/freesurfer/license.txt         \
        qsiprep-v1.0.1.sif /bids /out participant \
        -w /work \
        --fs-license-file /opt/freesurfer/license.txt \
        --skip-bids-validation \
        --participant-label $i \
        --session-id ses-01 \
        --bids-filter-file /code/bids_filter_dti.json \
        --eddy-config /code/eddy_params.json \
        --output-resolution 1.75 \
        --n-cpus 8 \
        --mem 16G \
        --separate-all-dwis \
        --anat-modality T2w \
        --denoise-method none \
        --unringing-method none \
        --distortion-group-merge concat \
        --pepolar-method TOPUP
EOF

    bsub bsub_qsiprep_$i.sh
    done
