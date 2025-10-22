import os
import json
import re
import glob

def fix_intended_for_field(bids_root):
    for root, dirs, files in os.walk(bids_root):
        if os.path.basename(root) == 'fmap':
            for file in files:
                if file.endswith('epi.json'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r') as f:
                            data = json.load(f)

                        # Normalize path for macOS compatibility
                        normalized_path = os.path.normpath(file_path)

                        # Extract subject and session identifiers
                        subject_match = re.search(r'sub-(\w+)', normalized_path)
                        session_match = re.search(r'ses-(\w+)', normalized_path)

                        if not subject_match:
                            print(f"Could not find subject in: {file_path}")
                            continue

                        subject = subject_match.group(1)
                        session = session_match.group(1) if session_match else None

                        inferred_paths = []
                        if subject.startswith('P'):
                            if session:
                                inferred_paths = [f"sub-{subject}/ses-{session}/dwi/sub-{subject}_ses-{session}_dwi.nii.gz"]
                            else:
                                inferred_paths = [f"sub-{subject}/dwi/sub-{subject}_dwi.nii.gz"]
                        elif subject.startswith('E'):
                            dwi_dir = os.path.join(bids_root, f"sub-{subject}", f"ses-{session}" if session else "", "dwi")
                            if os.path.isdir(dwi_dir):
                                abcd_files = glob.glob(os.path.join(dwi_dir, "*ABCD*.nii.gz"))
                                inferred_paths = [
                                    os.path.relpath(path, bids_root).replace("\\", "/") for path in abcd_files
                                ]

                        if not inferred_paths:
                            print(f"No DWI path found for {file_path}")
                            continue

                        # Update IntendedFor field
                        if 'IntendedFor' in data and isinstance(data['IntendedFor'], list):
                            cleaned = [path.replace('bids::', '') for path in data['IntendedFor']]
                            if not cleaned:
                                data['IntendedFor'] = inferred_paths
                                print(f"Filled empty IntendedFor in: {file_path}")
                            elif cleaned != data['IntendedFor']:
                                data['IntendedFor'] = cleaned
                                print(f"Cleaned IntendedFor in: {file_path}")
                            else:
                                print(f"No change needed: {file_path}")
                        else:
                            data['IntendedFor'] = inferred_paths
                            print(f"Added IntendedFor to: {file_path}")

                        # Save updated JSON
                        with open(file_path, 'w') as f:
                            json.dump(data, f, indent=4)

                    except Exception as e:
                        print(f"Error processing {file_path}: {e}")

# Example usage
bids_directory = '/Volumes/LaCie/Projects/elgan_dti/data'
fix_intended_for_field(bids_directory)
