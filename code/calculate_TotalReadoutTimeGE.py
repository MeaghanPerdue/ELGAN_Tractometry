#!/bin/bash
# Calculate the TotalReadoutTime for GE DWI scans based on info from DICOMS headers
# Following methods explained by Chris Rorden dcm2niix: <https://github.com/rordenlab/dcm2niix/tree/master/GE#total-readout-time> 

# To print dicom header info using python
# import pydicom
# df=pydicom.filereader.dcmread('AnyDicomFileFromDWISeries.dcm')
# print(df)

### Relevant fields ###
### Site 310 ###
# (0018, 1310) Acquisition Matrix                  US: [160, 0, 0, 160]
# (0018, 0022) Scan Options                        CS: ['SAT_GEMS', 'EPI_GEMS', 'FILTERED_GEMS', 'ACC_GEMS', 'PFF', 'FS']
# (0043, 102c) [Effective echo spacing]            SS: 792
# (0043, 1083) [Asset R Factors]                   DS: [1, 1]

### Site 320 ###
# (0018, 1310) Acquisition Matrix                  US: [0, 1600, 1600, 0]
# (0018, 0022) Scan Options                        CS: ['SAT_GEMS', 'EPI_GEMS', 'ACC_GEMS', 'PFF', 'FS']
# (0043, 102c) [Effective echo spacing]            SS: 732
# (0043, 1083) [Asset R Factors]                   DS: [0.5, 1]

# Set values according to DICOMS fields
ASSET_R_factor = 1 #reciprocal of 1st value in "0043,1083"
AcquisitionMatrixPE = 160 #3rd or 4th value in "0018,1310" (whichever is non-zero)
EchoSpacingMicroSecondsGE = 792 #us
Round_factor = 4 #because "0018,0022" contains "PFF"; otherwise = 2

# Set ReconMatrixPE value according to JSON Sidecar File from dcm2niix
ReconMatrixPE = 256

# Calculate intermediates
import math
NotPhysicalNumberOfAcquiredPELinesGE = (math.ceil((1/Round_factor) * AcquisitionMatrixPE / ASSET_R_factor) * Round_factor) 
NotPhysicalTotalReadOutTimeGE = (NotPhysicalNumberOfAcquiredPELinesGE - 1) * EchoSpacingMicroSecondsGE * 1e-6
EffectiveEchoSpacing = NotPhysicalTotalReadOutTimeGE / (AcquisitionMatrixPE - 1) 

TotalReadoutTime = EffectiveEchoSpacing * (ReconMatrixPE - 1)
print(TotalReadoutTime)