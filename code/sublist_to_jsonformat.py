import json

# Paste your newline-separated subject list here
subject_list_raw = '''
sub-E1600071G
sub-E1600121J
sub-E1600151G
sub-E1600241F
sub-E1600251E
sub-E1600281B
sub-E1600291A
sub-E1600331E
sub-E1600411E
sub-E1600431C
sub-E1600461L
sub-E1600491I
sub-E1600501D
sub-E1600521B
sub-E1600531A
sub-E1600601A
sub-E1600602K
sub-E1600641I
sub-E1600642G
sub-E1600652F
sub-E1600661G
sub-E1600692B
sub-E1600702I
sub-E1600721I
sub-E1600722G
sub-E1600831F
sub-E1600902E
sub-E1600903C
'''

# Convert to list and strip 'sub-' prefix
subject_list = [line.strip().replace("sub-", "") for line in subject_list_raw.splitlines() if line.strip()]
participant_labels_json = json.dumps({"participant_labels": subject_list}, indent=4)

print(participant_labels_json)