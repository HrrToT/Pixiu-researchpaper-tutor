"""Literal answer anchors for requested limits, never a semantic approval."""
import json
from collections import Counter


def enabled(record):
    return (type(record.get('coverageLimitContractVersion')) is int
        and record['coverageLimitContractVersion']==1
        and type(record.get('coverageInstructionsContractVersion')) is int
        and record['coverageInstructionsContractVersion']==1
        and type(record.get('requestCoverageContractVersion')) is int
        and record['requestCoverageContractVersion'] in (3,4,5))


GUIDANCE = '''For EVERY check with responseType="limitation", additionally return
limitSpans:[{"claimId":"bound accepted ID","field":"text|conditions",
"excerpt":"exact contiguous answer wording that states the requested limit"}].
All other checks OMIT limitSpans. Keep the ordinary bindings and status/reason.
covered needs nonempty limitSpans from THAT check's bound accepted fields. For
partial/missing use actual relevant spans if present, otherwise []. Never quote
source evidence, rejected drafts, request text or your own explanation as answer.
Use the minimum sufficient exact spans, not whole fields unless necessary.
An unstated guarantee is NOT an explicit boundary. Do not infer "implicitly limits"
from silence. Read whether the actual words answer the requested applicability,
assumptions, evidence limit or stronger conclusion not established. Do not demand
all these categories when only one was requested, an exhaustive condition list,
author-wide absence, a new experiment or a synonymous limitation label. Several
accepted points may jointly suffice. A literal match alone grants no semantic
coverage; irrelevant numbers, mechanism descriptions or names cannot stand in
for the requested limit. Read all accepted prose before declaring it absent.
'''


def validate(spans, claims, bindings, *, covered):
    errors=[]
    if not isinstance(spans,list):return ['invalid_limit_spans']
    if covered and not spans:errors.append('missing_explicit_limit_span')
    counts=Counter(c.get('claimId') for c in claims if isinstance(c,dict) and isinstance(c.get('claimId'),str))
    known={c['claimId']:c for c in claims if isinstance(c,dict) and isinstance(c.get('claimId'),str) and counts[c['claimId']]==1}
    allowed={(b.get('claimId'),b.get('field')) for b in bindings if isinstance(b,dict)
             and isinstance(b.get('claimId'),str) and isinstance(b.get('field'),str)}
    seen=set()
    for span in spans:
        if (not isinstance(span,dict) or set(span)!={'claimId','field','excerpt'}
            or not all(isinstance(span[k],str) for k in span)
            or not span['excerpt'].strip()):
            errors.append('invalid_limit_span');continue
        key=(span['claimId'],span['field']);text=None
        claim=known.get(span['claimId'])
        if key not in allowed or claim is None or span['field'] not in ('text','conditions'):
            errors.append('limit_span_outside_accepted_binding');continue
        if span['field']=='text':text=claim.get('text')
        elif isinstance(claim.get('conditions'),dict) and claim['conditions']:
            text=json.dumps(claim['conditions'],ensure_ascii=False,sort_keys=True)
        if not isinstance(text,str) or span['excerpt'] not in text:
            errors.append('limit_span_not_in_answer')
        identity=(*key,span['excerpt'])
        if identity in seen:errors.append('duplicate_limit_span')
        seen.add(identity)
    return list(dict.fromkeys(errors))
