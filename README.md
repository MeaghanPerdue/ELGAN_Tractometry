# ELGAN DTI Tractometry Project
Author: Meaghan V. Perdue \
October 2025

## Overview
This project contains data processing scripts and data for DTI tractometry analysis of the Extremely Low Gestational Age Newborns (ELGAN) Study at the ~15-year-old MRI visit. ELGAN study details can be found here: \
<https://doi.org/10.1016/j.earlhumdev.2009.08.060> \
<https://doi.org/10.1016/j.jaac.2021.12.008> \
<https://doi.org/10.1148/radiol.210385> \

ELGAN is a multi-site study. This dataset is organized with separate BIDS subfolders for each site. DTI data was collected at b=1000 with 15-16 diffusion gradient directions with no reverse phase encoded B0s. Several sites additionally acquired a multi-shell HARDI sequence based on the ABCD protocol, which are processed separately from the main DTI acquisition.

Data from the Pediatric Imaging Neurocognition and Genetics Data Repository (PING; <https://10.1016/j.neuroimage.2015.04.057>) is included as a full-term comparison sample.

## Processing Steps
Preprocessing is performed using qsiprep v1.0.1 using GPU nodes on a high performance computing cluster. \
Model fitting, tractography, and tract profiling are computed with pyAFQ using both the AFQ-waypoints tract segmentation method and the Recobundles tract segmentation method for comparison.

