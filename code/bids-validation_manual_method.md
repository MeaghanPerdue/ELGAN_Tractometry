# Manual and semi-scripted methods for correcting issues from BIDS validation
1. Run BIDS validator in the browser: <https://bids-standard.github.io/bids-validator/> \
2. ERROR: SCANS_FILENAME_NOT_MATCH_DATASET \
3. Open each scans.tsv file individually and list subjects' folder contents to check for mis-matches \
4. Manually correct scans.tsv file to match actual file contents \
5. If the same issue occurs across multiple subjects, run a python script to regenerate all scans.tsv files, e.g. regenerate_scans_tsv.py