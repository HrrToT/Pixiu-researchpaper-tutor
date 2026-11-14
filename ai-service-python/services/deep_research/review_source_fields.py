"""Resolve reviewer references against unchanged fields actually sent on the wire."""
from copy import deepcopy

from services.deep_research.audit_source_fields import resolve
from services.deep_research.contracts import DeepResearchError


GUIDANCE='''Reviewer reasonParts encoding with original-field references:
Return reasonParts instead of reason and diagnosticFacts. Never emit both encodings.
Use at most16 nonempty segments, each with exactly one of these shapes:
{"text":"brief assessment derived from the target, no new source fact"}
{"text":"source fact used in this assessment","evidenceId":"own E ID","path":["quote"]}
The second form references the unchanged original field; do not retype formulas or
long excerpts. Allowed paths: ["quote"], ["sourceContext"] when a string was supplied,
or ["sourceContext","before"] / ["sourceContext","after"] when actually supplied.
Choose the exact own evidence ID AND field that supports this statement. A reference
to an unrelated field, metadata, hidden context or another target is not support.
The older exact excerpt form remains allowed, but any excerpt must match that field.
Every added source fact, including corrections and numerical formulas, needs a source
reference IN ITS OWN SEGMENT. Plain segments cannot introduce unbound facts or numbers.
New numbers must occur in both that segment's text and its referenced original field;
numerical coincidence alone does not prove the statement. Do not add unnecessary
formulas, default parameters, line numbers or new claims to explain a short verdict.
Every segment is retained. These references do not decide scientific support: the
whole-claim semantic decision, all scope/condition/source/numerical audits and negative
decisions remain unchanged. Missing support must remain unresolved.'''


def valid_reference(part):
    return (isinstance(part,dict) and set(part)=={'text','evidenceId','path'}
            and isinstance(part['text'],str) and bool(part['text'].strip())
            and isinstance(part['evidenceId'],str) and bool(part['evidenceId'].strip())
            and isinstance(part['path'],list)
            and part['path'] in [['quote'],['sourceContext'],['sourceContext','before'],['sourceContext','after']])


def resolve_response(rows, claims, visible, reverse):
    """Only expand the new reference form; never repair an explicit bad excerpt.

    This runs after prompt fitting. Transport-level syntax validation has no
    source permissions and must leave the original model response unchanged.
    """
    result=deepcopy(rows)
    targets={c['claimId']:c for c in claims}
    for row in result if isinstance(result,list) else [result]:
        if not isinstance(row,dict) or not isinstance(row.get('reasonParts'),list):
            continue  # The ordinary response decoder rejects malformed envelopes.
        claim=targets.get(row['claimId']) if isinstance(row.get('claimId'),str) else None
        if claim is None:
            raise DeepResearchError('invalid_verification_response','审核字段引用没有对应的本轮目标。',{'responseState':'received_invalid'})
        own={e['evidenceId']:e for e in visible if e.get('evidenceId') in claim.get('evidenceRefs',[])}
        for part in row['reasonParts']:
            if not isinstance(part,dict) or set(part)!={'text','evidenceId','path'}:
                continue  # Legacy explicit excerpts still undergo their original checks.
            if not valid_reference(part):
                raise DeepResearchError('invalid_verification_response','审核原文字段引用结构无效。',{'responseState':'received_invalid'})
            source=resolve({'evidenceId':reverse.get(part['evidenceId'],part['evidenceId']),
                            'path':part['path']},own)
            if source is None:
                raise DeepResearchError('invalid_verification_response','审核原文字段未在本条可见材料中提供。',{'responseState':'received_invalid'})
            part['excerpt']=source[1]
    return result
