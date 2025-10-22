def create_key(template, outtype=('nii.gz',), annotation_classes=None):
    if not template:
        raise ValueError("Template must be a valid format string")
    return template, outtype, annotation_classes

def infotodict(seqinfo):
    # Define BIDS keys
    t1w_low_res = create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_acq-lowres_T1w')
    t1w_high_res = create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_T1w')
    t1w_se       = create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_acq-se_T1w')
    t2w_pdt2     = create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_acq-PDT2_T2w')
    pdw_pdt2     = create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_acq-PDT2_PDw')
    dwi_15dir    = create_key('sub-{subject}/{session}/dwi/sub-{subject}_{session}_dwi')
    dwi_A1       = create_key('sub-{subject}/{session}/dwi/sub-{subject}_{session}_acq-ABCD1_dwi')
    dwi_A2       = create_key('sub-{subject}/{session}/dwi/sub-{subject}_{session}_acq-ABCD2_dwi')
    dwi_b0      = create_key('sub-{subject}/{session}/dwi/sub-{subject}_{session}_acq-B0_dwi')
    rest         = create_key('sub-{subject}/{session}/func/sub-{subject}_{session}_task-rest_bold')
    

    info = {key: [] for key in [t1w_low_res, t1w_high_res, t1w_se, t2w_pdt2, pdw_pdt2,
                                dwi_15dir, dwi_A1, dwi_A2, dwi_b0, rest]}

    for s in seqinfo:
        # Skip derived maps
        if any(tag in s.image_type for tag in ['ADC', 'FA', 'EADC']):
            continue

        assign = None
        name = s.series_description or s.protocol_name or ""

        # Classification logic based on TE, TR, dimensions
        if 'SMARTBRAIN' in name.upper():
            assign = t1w_low_res
        elif 'MPRAGE' in name.upper() or (2.5 < s.TE < 3.5 and s.TR < 0.01 and s.dim3 in [226, 55, 3]):
            assign = t1w_high_res
        elif 'SE-TSE' in name.upper() or ('SE' in s.image_type and s.TE < 30 and s.dim3 == 81):
            assign = t1w_se
        elif 'DE-TSE' in name.upper() or (90 < s.TE < 110 and s.dim3 == 160 and s.TR > 5):
            assign = t2w_pdt2
        elif 'DE-TSE' in name.upper() or (s.TE < 20 and s.dim3 == 160 and s.TR > 5):
            assign = pdw_pdt2
        elif 'DTI_MEDIUM_ISO' in name.upper() or (s.dim3 in [1021, 4132] and s.TR > 5):
            assign = dwi_15dir
        elif 'DTI_MEDIUM_ISO' in name.upper() and s.TR < 0:
            assign = dwi_b0
        elif 'DTI 1' in name:
            assign = dwi_A1
        elif 'DTI 2' in name:
            assign = dwi_A2
        elif 'RSFMRI' in name.upper() or (s.dim4 > 10000 and s.TR > 0.7 and s.dim1 == 96 and s.dim2 == 96):
            assign = rest

        # Assign or fallback to misc
        if assign:
            print("YYYYY to %r", assign)
            info[assign] = [s.series_id]
        else:
            print("EEEEE was not assigned anywhere!")

    return info
