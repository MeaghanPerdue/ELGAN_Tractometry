#!/bin/bash
# copy bids data to hpc for processing, including selected subjects

    rsync -av ../data/site-310/dataset_description.json meaghan.perdue-umw@hpc:/home/meaghan.perdue-umw/elgan_dti/data
    rsync -av ../data/site-310/participants.tsv meaghan.perdue-umw@hpc:/home/meaghan.perdue-umw/elgan_dti/data
    rsync -av ../data/site-310/participants.json meaghan.perdue-umw@hpc:/home/meaghan.perdue-umw/elgan_dti/data
    rsync -av ../data/site-310/scans.json meaghan.perdue-umw@hpc:/home/meaghan.perdue-umw/elgan_dti/data

for i in $(cat tmpsubs2.txt); do
    rsync -av ../data/site-310/${i} meaghan.perdue-umw@hpc:/home/meaghan.perdue-umw/elgan_dti/data
    done
    