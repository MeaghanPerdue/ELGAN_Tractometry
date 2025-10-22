    #!/bin/bash
    #BSUB -n 8				      
    #BSUB -R "rusage[mem=32G]"                               
    #BSUB -q gpu	
    #BSUB -m V100		     
    #BSUB -W 02:00



    # submit job to run a single participant through qsiprep for DTI only


    module load apptainer

    apptainer run --containall --writable-tmpfs --nv         -B /home/meaghan.perdue-umw/elgan_dti/code:/code,/home/meaghan.perdue-umw/elgan_dti/data:/bids,/home/meaghan.perdue-umw/elgan_dti/data/derivatives/qsiprep:/out,/home/meaghan.perdue-umw/elgan_dti/work:/work,license.txt:/opt/freesurfer/license.txt         qsiprep-v1.0.1.sif         /bids /out participant         -w /work         --fs-license-file /opt/freesurfer/license.txt         --skip-bids-validation         --participant-label E1600601A         --session-id ses-03         --bids-filter-file /code/bids_filter_dti.json         --eddy-config /code/eddy_params.json         --output-resolution 1.75         --n-cpus 8         --mem 32G         --separate-all-dwis         --anat-modality T2w         --denoise-method none         --unringing-method rpg         --use-syn-sdc error         --force-syn
