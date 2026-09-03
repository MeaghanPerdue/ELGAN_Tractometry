#!/bin/bash
# copy bids data to hpc for processing, including selected subjects

    rsync -av ../data/site-220/dataset_description.json meaghan.perdue-umw@hpc:/home/meaghan.perdue-umw/elgan_dti/data
    rsync -av ../data/site-220/participants.tsv meaghan.perdue-umw@hpc:/home/meaghan.perdue-umw/elgan_dti/data
    rsync -av ../data/site-220/participants.json meaghan.perdue-umw@hpc:/home/meaghan.perdue-umw/elgan_dti/data
    rsync -av ../data/site-220/scans.json meaghan.perdue-umw@hpc:/home/meaghan.perdue-umw/elgan_dti/data
    rsync -av ../data/site-220/derivatives/qsiprep/dataset_description.json meaghan.perdue-umw@hpc:/home/meaghan.perdue-umw/elgan_dti/data/derivatives/qsiprep
    rsync -av tmpsubs.txt meaghan.perdue-umw@hpc:/home/meaghan.perdue-umw/elgan_dti/code


for i in $(cat tmpsubs.txt); do
    rsync -av ../data/site-220/derivatives/qsiprep/${i} meaghan.perdue-umw@hpc:/home/meaghan.perdue-umw/elgan_dti/data/derivatives/qsiprep
    rsync -av ../data/site-220/derivatives/afq/${i} meaghan.perdue-umw@hpc:/home/meaghan.perdue-umw/elgan_dti/data/derivatives/afq
    done
    