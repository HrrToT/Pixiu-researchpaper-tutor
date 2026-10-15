"""Normalize only an unambiguous report container; never repair claim content."""
from copy import deepcopy


def normalize_synthesis_container(value):
    if isinstance(value, dict):
        return value, 'object'
    if not isinstance(value, list) or not value:
        return None, None
    sections, claims = [], []
    for row in value:
        if not isinstance(row, dict):
            return None, None
        if set(row) == {'title', 'claimIds'}:
            if (not isinstance(row['title'], str) or not row['title'].strip()
                    or not isinstance(row['claimIds'], list) or not row['claimIds']
                    or any(not isinstance(key, str) or not key.strip() for key in row['claimIds'])):
                return None, None
            sections.append(row)
        elif ('title' not in row and 'claimIds' not in row
                and isinstance(row.get('claimId'), str) and row['claimId'].strip()
                and isinstance(row.get('text'), str) and row['text'].strip()
                and isinstance(row.get('kind'), str)
                and row['kind'] in {'reported', 'inference', 'hypothesis', 'proposal', 'suggestion'}
                and isinstance(row.get('evidenceRefs'), list)
                and all(isinstance(ref, str) and ref.strip() for ref in row['evidenceRefs'])):
            claims.append(row)
        else:
            return None, None
    if not sections or not claims:
        return None, None
    identities = [row['claimId'] for row in claims]
    references = [key for row in sections for key in row['claimIds']]
    if (len(identities) != len(set(identities)) or len(references) != len(set(references))
            or set(references) != set(identities)):
        return None, None
    return deepcopy({'sections': sections, 'claims': claims}), 'mixed_section_claim_array'
