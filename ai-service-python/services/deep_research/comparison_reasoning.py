"""Trace comparative premises without treating unknown settings as differences.

The audit validates identities/quotations and the shape of a comparison. The
independent semantic check still decides whether those premises imply the text.
It is internal evidence, never extra user-facing prose or factual permission.
"""
import json
import re


def enabled(record):
    return type(record.get('comparisonReasoningContractVersion')) is int and record['comparisonReasoningContractVersion']==1


GUIDANCE='''For a requested comparison/check, lead with the qualified judgement, then the
minimum sufficient evidence and its limits. A list of cells alone is not a judgement.
Use a small relevant numerical example, not whole rows that displace requested limits.
Separate metric directions and data groups; similar quality does not mean every metric
is unchanged or worse. State only the evaluated scope, not author-wide absence.
Before explaining why two measurements differ or cannot be compared, check the premise
of the user's question. A why question is not evidence that its premise is true.
Distinguish documented matching conditions, demonstrated differences and alignment not
established by the available evidence. Unknown hardware/data/resolution is NOT evidence
of different hardware/data/resolution, even when phrased as "may differ" in a causal reason.
A shared hardware label alone does not establish a controlled comparison either.
Do not turn unverified alignment into categorical impossibility or an inherent speedup.
When alignment is not established, state that limitation and the conditions needed for
a valid comparison. Prefer results measured in the same reported experiment; preserve
method variants and original versus re-trained baseline provenance. Do not infer cross-
study causal gains from raw ratios. If a requested premise is too strong, qualify it.
Every factual premise must be supported by this claim's own citations; a generic warning
or another claim's sources cannot fill an unsupported comparison premise.'''


def _identity(item):
    # The verifier's bounded projection uses workId/versionId, while persisted
    # evidence uses sourceWorkId/sourceVersionId. Both retain the same identity.
    return item.get('sourceWorkId',item.get('workId')),item.get('sourceVersionId',item.get('versionId'))


def audit_scope(claim,evidence):
    if claim.get('kind') not in {'reported','inference'}:
        return None
    refs=set(claim.get('evidenceRefs',[]))
    own=[e for e in evidence if e.get('evidenceId') in refs]
    identities={_identity(e) for e in own if all(_identity(e))}
    if len(identities)>1:
        return 'cross_study'
    bindings=claim.get('tableBindings',[])
    cells={(b.get('evidenceId'),b.get('rowNumber')) for b in (bindings if isinstance(bindings,list) else [])
           if isinstance(b,dict)}
    if len(cells)>1:
        return 'within_study'
    return None


def audit_prompt(targets):
    return '\n'+GUIDANCE+'''
For the following comparative targets, a passed verdict MUST also include comparisonAudit.
Target scopes (metadata, not evidence): '''+json.dumps(targets,separators=(',',':'))+'''
Schema:
{"scope":"exact target scope","alignment":"established|not_established|different",
 "supportsClaim":true,"premises":[{"evidenceId":"own E ID","quote":"exact own quotation excerpt"}],
 "differences":[{"dimension":"named compared condition","left":{"evidenceId":"own E ID","quote":"exact excerpt","value":"literal condition value"},
                 "right":{"evidenceId":"own E ID","quote":"exact excerpt","value":"literal condition value"}}]}
Use only original own quote/sourceContext actually supplied. For cross_study, bind an
actual premise from EACH source/version used by the claim; source counts are not proof.
Choose different only when both sides explicitly establish distinct values of the SAME
condition for the relevant subjects/protocols. Different spellings/aliases do not prove a
different setting. Nonempty differences are required then; otherwise differences=[].
Missing detail establishes not_established, never different. A within-study reported
comparison can be bounded to its table/protocol without claiming all settings controlled.
supportsClaim=true ONLY if the visible claim's conclusion AND causal explanation follow
from the audited premises at that scope. Reject a conditional-sounding speculation used
as an established reason, or an unconditional impossibility based on unknown alignment.
For metric comparisons check direction and each group, not only numerical closeness.
If no supported audit is possible return status=failed with the specific missing premise;
do not invent an audit or cite irrelevant quotations to satisfy the schema.
'''


def _normalized(text):
    return re.sub(r'\s+',' ',text).strip()


def validate_audit(claim,verdict,evidence):
    scope=audit_scope(claim,evidence)
    if scope is None:
        return []
    audit=verdict.get('comparisonAudit')
    if (not isinstance(audit,dict) or set(audit)!={'scope','alignment','supportsClaim','premises','differences'}
            or audit.get('scope')!=scope or audit.get('alignment') not in {'established','not_established','different'}
            or audit.get('supportsClaim') is not True):
        return ['comparison_premise_not_established']
    own={e['evidenceId']:e for e in evidence if e.get('evidenceId') in claim.get('evidenceRefs',[])}

    def bound(row,with_value=False):
        keys={'evidenceId','quote','value'} if with_value else {'evidenceId','quote'}
        if not isinstance(row,dict) or set(row)!=keys:
            return None
        if not isinstance(row.get('evidenceId'),str):
            return None
        item=own.get(row['evidenceId'])
        quote=row.get('quote')
        if not item or not isinstance(quote,str) or not quote.strip():
            return None
        # Only the same bounded context made visible to the verifier may bind.
        from services.deep_research.selection import surrounding_context
        available=[item.get('quote',''),surrounding_context(item)]
        if not any(_normalized(quote) in _normalized(text) for text in available if isinstance(text,str)):
            return None
        if with_value and (not isinstance(row.get('value'),str) or not row['value'].strip()
                           or _normalized(row['value']) not in _normalized(quote)):
            return None
        return item

    premises=audit['premises']
    if not isinstance(premises,list) or not premises:
        return ['comparison_premise_missing']
    bound_premises=[bound(row) for row in premises]
    if any(item is None for item in bound_premises):
        return ['comparison_premise_quote_mismatch']
    if scope=='cross_study' and {_identity(e) for e in bound_premises}!={_identity(e) for e in own.values()}:
        return ['comparison_source_premise_missing']
    if scope=='within_study' and {b.get('evidenceId') for b in claim.get('tableBindings',[]) if isinstance(b,dict)}-{
            row['evidenceId'] for row in premises}:
        return ['comparison_row_premise_missing']
    differences=audit['differences']
    if not isinstance(differences,list):
        return ['invalid_comparison_difference']
    if audit['alignment']!='different':
        return [] if not differences else ['unknown_alignment_is_not_difference']
    if not differences:
        return ['comparison_difference_missing']
    for row in differences:
        if (not isinstance(row,dict) or set(row)!={'dimension','left','right'}
                or not isinstance(row.get('dimension'),str) or not row['dimension'].strip()):
            return ['invalid_comparison_difference']
        left,right=bound(row['left'],True),bound(row['right'],True)
        if left is None or right is None:
            return ['comparison_difference_quote_mismatch']
        if scope=='cross_study' and _identity(left)==_identity(right):
            return ['comparison_difference_same_source']
        if _normalized(row['left']['value']).casefold()==_normalized(row['right']['value']).casefold():
            return ['comparison_values_not_different']
    return []
