#!/bin/bash
# Export group-wise Tract Profiles csv file for Tractable analysis
# run locally via Docker after pulling from HPC 
# use in cases where a subset of participants were re-run after intial pyAFQ run
# update path to bids site appropriately

docker run --rm \
  -v /Volumes/LaCie/Projects/elgan_dti/data/site-330:/bids \
  -v /Volumes/LaCie/Projects/elgan_dti/code:/code
  ghcr.io/nrdg/pyafq \
  /code/export_profiles_config.toml
