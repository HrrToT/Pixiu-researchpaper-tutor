"""Lossless reviewer reason segments; all scientific gates run after decoding."""
from copy import deepcopy
from services.deep_research.contracts import DeepResearchError

GUIDANCE='''Reviewer reasonParts encoding:
Return reasonParts instead of reason and diagnosticFacts. Do not return both encodings.
reasonParts is a nonempty array of at most16 segments. A segment has either exactly
{"text":"brief assessment derived from the target, no new source fact"} or exactly
{"text":"a source fact used in this assessment","evidenceId":"own E ID",
 "path":["quote"],"excerpt":"exact contiguous source words supporting this text"}.
The server concatenates EVERY text in order into the reason and derives diagnosticFacts
from bound segments. Write each source fact once, including numerical corrections and
necessary conditions, with its original-source binding in that same segment. New numbers
still must occur in its text AND original excerpt. Plain segments cannot introduce an
unbound correction. Source metadata/IDs and target assertions do not prove source facts.
Allowed source paths remain quote,sourceContext.before,sourceContext.after. Never invent
a source ID, omitted premise or unreadable expression. Missing support stays unresolved.
This only encodes the explanation: the whole-claim decision and EVERY independent
source,scope,comparison,condition and numerical check still apply.'''


def expand(row):
    if (not isinstance(row,dict) or 'reason' in row or 'diagnosticFacts' in row
            or not isinstance(row.get('reasonParts'),list) or not 1<=len(row['reasonParts'])<=16):
        raise DeepResearchError('invalid_verification_response','审核说明片段缺失或存在冲突编码。',{'responseState':'received_invalid'})
    texts=[];facts=[]
    for part in row['reasonParts']:
        if (not isinstance(part,dict) or set(part) not in ({'text'},{'text','evidenceId','path','excerpt'})
                or not isinstance(part.get('text'),str) or not part['text'].strip()):
            raise DeepResearchError('invalid_verification_response','审核说明片段结构无效。',{'responseState':'received_invalid'})
        texts.append(part['text'])
        if 'evidenceId' in part:
            # Validation of original source membership, paths, literal excerpts,
            # introduced numbers and actual semantics remains downstream.
            facts.append({'statement':part['text'],**{k:deepcopy(part[k]) for k in ('evidenceId','path','excerpt')}})
    return {**{k:deepcopy(v) for k,v in row.items() if k!='reasonParts'},
            'reason':'\n'.join(texts),'diagnosticFacts':facts}
