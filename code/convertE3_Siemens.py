import os


def create_key(template, outtype=('nii.gz',), annotation_classes=None):
    if template is None or not template:
        raise ValueError('Template must be a valid format string')
    return template, outtype, annotation_classes


def infotodict(seqinfo):
    """Heuristic evaluator for determining which runs belong where

    allowed template fields - follow python string module:

    item: index within category
    subject: participant id
    seqitem: run number during scanning
    subindex: sub index within group
    """

    t1w_mprage =   create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_T1w')
    t1w_mprage_norm =   create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_rec-NORM_T1w')
    t1w_se =       create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_acq-se_T1w')
    t2w_pdt2 =     create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_acq-PDT2_T2w')
    pdw_pdt2 =     create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_acq-PDT2_PDw')
    dwi_sbref =    create_key('sub-{subject}/{session}/fmap/sub-{subject}_{session}_acq-sbref_dir-AP_epi')
    dwi_16dir =    create_key('sub-{subject}/{session}/dwi/sub-{subject}_{session}_dir-AP_dwi')
    dwi_16dir_vec2 = create_key('sub-{subject}/{session}/dwi/sub-{subject}_{session}_acq-vector2_dir-AP_dwi')
    rest =         create_key('sub-{subject}/{session}/func/sub-{subject}_{session}_task-rest_bold')
    bold_sbref =   create_key('sub-{subject}/{session}/fmap/sub-{subject}_{session}_acq-sbref_dir-AP_epi')
    de_ge =        create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_MEGRE')

    data = create_key('run{item:03d}')
    info = {data: []}
    last_run = len(seqinfo)

    for s in seqinfo:
        """
        The namedtuple `s` contains the following fields:

        * total_files_till_now
        * example_dcm_file
        * series_id
        * dcm_dir_name
        * unspecified2
        * unspecified3
        * dim1
        * dim2
        * dim3
        * dim4
        * TR
        * TE
        * protocol_name
        * is_motion_corrected
        * is_derived
        * patient_id
        * study_description
        * referring_physician_name
        * series_description
        * image_type
        """
        if any(tag in s.image_type for tag in ['ADC', 'FA', 'EADC']):
            continue
        
        print("XXXXX %r %r %r %r" % (s.series_description, s.series_id, s.protocol_name, s.TE))
        assign = None
        name = s.series_description or s.protocol_name

        if 'GE-EPI' in name and s.dim4 == 270:
            assign = rest
        elif 'GE-EPI' in name and s.dim4 == 1:
            assign = bold_sbref
        elif 'MPRAGE' in name.upper() or 'T1W_MPR' in name.upper() and 'ORIGINAL' in s.image_type and 'NORM' not in s.image_type:
            assign = t1w_mprage
        elif 'MPRAGE' in name.upper() or 'T1W_MPR' in name.upper() and 'NORM' in s.image_type:
            assign = t1w_mprage_norm
        elif 'TSE_TB' in name.upper() or 'SE-TSE' in name.upper() and s.TE < 30:
            assign = t1w_se
        elif 'DMRI_SBREF' in name.upper():
            assign = dwi_sbref
        elif 'DMRI' in name.upper() and 'VECTOR2' not in name.upper() and s.dim4 > 1:
            assign = dwi_16dir
        elif 'dMRI' in name and 'VECTOR2' in name.upper() and s.dim4 > 1:
            assign = dwi_16dir_vec2
        elif 'DE-TSE' in name.upper(): 
            if s.TE < 20:
                assign = pdw_pdt2
            elif 90 < s.TE < 110:
                assign = t2w_pdt2
        elif 'T2W-GE' in name.upper():
            assign = de_ge
        if assign:
            print("YYYYY to %r", assign)
            info[assign] = [s.series_id]
        else:
            print("EEEEE was not assigned anywhere!")
        """
	DE-TSE
	SE-TSE
	DTI_medium_iso
	MPRAGE
	rsfMRI 
	RESET
        """

#        info[data].append(s.series_id)
    return info
