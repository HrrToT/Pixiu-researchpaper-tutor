"""Describe available answer fields; never repair or approve audit bindings."""
from collections import Counter


def build(claims, metadata):
    counts = Counter(c.get('claimId') for c in claims if isinstance(c.get('claimId'), str))
    records = metadata.get('sourceAccessRecords', {})
    records=records if isinstance(records,dict) else {}
    rows = []
    for claim in claims:
        identity = claim.get('claimId')
        if not isinstance(identity, str) or counts[identity] != 1:
            continue
        fields = []
        if isinstance(claim.get('text'), str) and claim['text'].strip():
            fields.append('text')
        if isinstance(claim.get('conditions'), dict) and claim['conditions']:
            fields.append('conditions')
        refs = claim.get('evidenceRefs', [])
        if (metadata.get('sourceAccessSummary') and type(metadata.get('taskSourceAccessContractVersion')) is int and metadata['taskSourceAccessContractVersion'] == 1
                and refs and all(records.get(ref) in {'fulltext', 'abstract', 'user_note'} for ref in refs)):
            fields.append('sourceAccessSummary')
        rows.append({'claimId': identity, 'fields': fields})
    return rows


GUIDANCE = '''Answer binding catalog lists the ONLY available fields for each claim.
Choose the minimum real fields that support each check, not every catalog entry.
An absent or empty conditions object is not a field you may bind. Do not invent
conditions bindings to indicate that no extra conditions were requested.
sourceAccessSummary answers only an explicit access-disclosure command, never
scientific content. For a mixed original request bind actual scientific text plus
the server label when each is needed. Scientific criteria still require prose.
Do not claim covered merely because a field exists. Partial/missing checks must
identify actual missing content. Invalid fields remain invalid; do not repair them.'''
