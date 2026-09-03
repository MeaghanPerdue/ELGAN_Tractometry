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

    t1w_se =       create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_acq-se_T1w')
    t2w_pdt2 =     create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_acq-PDT2_T2w')
    pdw_pdt2 =     create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_acq-PDT2_PDw')
    dwi_16dir =    create_key('sub-{subject}/{session}/dwi/sub-{subject}_{session}_dwi')
    dwi_16dir_iso =    create_key('sub-{subject}/{session}/dwi/sub-{subject}_{session}_rec-iso_dwi')
    me_gre =    create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_MEGRE')

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
        
        print("XXXXX %r %r %r %r %r" % (s.series_id, s.protocol_name, s.dcm_dir_name, s.TE, s.TR))
        assign = None
        name = s.dcm_dir_name

        if 'AX DTI' in name.upper():
            assign = dwi_16dir
        elif 'ISOTROPIC' in name.upper():
            assign = dwi_16dir_iso
        elif 'DE-TSE' in name.upper() and s.TR > 5: 
            if s.TE < 30:
                assign = pdw_pdt2
            elif 90 < s.TE < 110:
                assign = t2w_pdt2
        elif 'DE-FSE' in name.upper() and s.TR > 5: 
            if s.TE < 30:
                assign = pdw_pdt2
            elif 90 < s.TE < 110:
                assign = t2w_pdt2
        elif 'SE-TSE' in name.upper() and  s.TE < 30 and s.TR < 1:
            assign = t1w_se
        elif 'SE-FSE' in name.upper() and s.TE < 30 and s.TR < 1:
            assign = t1w_se
        elif 'DE-GRE' in name.upper(): 
                assign = me_gre
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
