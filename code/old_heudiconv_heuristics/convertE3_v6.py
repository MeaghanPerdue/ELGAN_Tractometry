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

    t1w_low_res =  create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_acq-lowres_T1w')
    t1w_high_res = create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_T1w')
    t1w_se =       create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_acq-se_T1w')
    t2w_pdt2 =     create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_acq-PDT2_T2w')
    pdw_pdt2 =     create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_acq-PDT2_PDw')
    dwi_15dir =    create_key('sub-{subject}/{session}/dwi/sub-{subject}_{session}_dwi')
    dwi_A1 =       create_key('sub-{subject}/{session}/dwi/sub-{subject}_{session}_acq-ABCD1_dwi')
    dwi_A2 =       create_key('sub-{subject}/{session}/dwi/sub-{subject}_{session}_acq-ABCD2_dwi')
    dwi_b0s =      create_key('sub-{subject}/{session}/dwi/sub-{subject}_{session}_acq-B0s_dwi')
    rest =         create_key('sub-{subject}/{session}/func/sub-{subject}_{session}_task-rest_bold')

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

        print("XXXXX %r %r %r %r" % (s.series_description, s.series_id, s.protocol_name, s.TE))
        assign = None
        name = s.series_description or s.protocol_name

        elif name == 'SmartBrain':
            assign = t1w_low_res
        elif name == 'rsfMRI 1':
            assign = rest
        elif 'MPRAGE' in name.upper():
            assign = t1w_high_res
        elif name in ['DTI_medium_iso']:
            assign = dwi_15dir
        elif name == 'DTI 1':
            assign = dwi_A1
        elif name == 'DTI 2':
            assign = dwi_A2
        elif name == 'DTI-EXTRA B0':
            assign = dwi_b0s
        elif name in ['DE-TSE', 'WIP DE-TSE']:
            if 90 < s.TE < 110:
               assign = t2w_pdt2
            elif s.TE < 20:
               assign = pdw_pdt2
        elif name in ['SE-TSE', 'WIP SE-TSE'] and s.TE < 30:
            assign = t1w_se
        
        if assign:
            print("YYYYY to %r", assign)
            info[assign] = [s.series_id]
        else:
            print("EEEEE was not assigned anywhere!")
        """
	SmartBrain
	DE-TSE
	SE-TSE
	DTI_medium_iso
	MPRAGE
	ME-FFE
	rsfMRI 1
	RESET
	DTI Fieldmap P
	DTI Fieldmap A
	DTI 1
	DTI 2
        """

#        info[data].append(s.series_id)
    return info
