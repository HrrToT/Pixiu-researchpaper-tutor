"""Lossless reviewer reason segments; all scientific gates run after decoding."""
from copy import deepcopy
from services.deep_research.contracts import DeepResearchError

MAX_REASON_PARTS = 24

GUIDANCE='''Reviewer reasonParts encoding:
Return reasonParts instead of reason and diagnosticFacts. Do not return both encodings.
Use a nonempty array of at most 16 segments. Summarize the verdict instead of restating each target clause.
A segment has either exactly
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

NO_NEW_EXPOSITORY_COUNTS = '''Describe required conditions or operations directly.
Keep quantities necessary to the verdict. Avoid adding a count of conditions,
steps, facts or reasons solely to summarize them. State the actual prerequisites
or operations without introducing a count.'''

SUPPORTED_WITHOUT_NARRATION = '''For scopeAudit.supported=true, return reasonParts:[]
with all required audit fields and bound premises. This is the exception to the
nonempty segment requirement. The cited premises record the basis for the verdict.
For scopeAudit.supported=false, return the concise, nonempty bound explanation.'''


def expand(row, *, field_references=False, compact_supported=False):
    if type(field_references) is not bool:raise ValueError('Invalid reviewer source-field policy')
    if type(compact_supported) is not bool:raise ValueError('Invalid compact review policy')
    if (not isinstance(row,dict) or 'reason' in row or 'diagnosticFacts' in row
            or not isinstance(row.get('reasonParts'),list) or len(row['reasonParts'])>MAX_REASON_PARTS
            or not compact_supported and not row['reasonParts']):
        raise DeepResearchError('invalid_verification_response','审核说明片段缺失或存在冲突编码。',{'responseState':'received_invalid'})
    if not row['reasonParts']:
        scope = row.get('scopeAudit')
        if (not isinstance(scope, dict) or scope.get('supported') is not True
                or not isinstance(scope.get('premises'), list) or not scope['premises']):
            raise DeepResearchError('invalid_verification_response','审核说明缺失，或支持判定缺少证据前提。',{'responseState':'received_invalid'})
        return {**{k:deepcopy(v) for k,v in row.items() if k!='reasonParts'},
                'reason':'审核返回了支持判定及证据前提。','diagnosticFacts':[]}
    texts=[];facts=[]
    for part in row['reasonParts']:
        from services.deep_research.review_source_fields import valid_reference
        reference=field_references and valid_reference(part)
        if (not isinstance(part,dict) or not reference and set(part) not in ({'text'},{'text','evidenceId','path','excerpt'})
                or not isinstance(part.get('text'),str) or not part['text'].strip()):
            raise DeepResearchError('invalid_verification_response','审核说明片段结构无效。',{'responseState':'received_invalid'})
        texts.append(part['text'])
        if 'evidenceId' in part:
            # Validation of original source membership, paths, literal excerpts,
            # introduced numbers and actual semantics remains downstream.
            # Syntax-only transport validation may retain an unresolved field
            # reference. It cannot pass the downstream literal diagnostic binder.
            keys=('evidenceId','path') if reference else ('evidenceId','path','excerpt')
            facts.append({'statement':part['text'],**{k:deepcopy(part[k]) for k in keys}})
    return {**{k:deepcopy(v) for k,v in row.items() if k!='reasonParts'},
            'reason':'\n'.join(texts),'diagnosticFacts':facts}
