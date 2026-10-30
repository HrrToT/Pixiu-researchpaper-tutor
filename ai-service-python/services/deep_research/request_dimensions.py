"""Split explicit requested deliverable dimensions, never scientific entities."""
import re

_DIMENSION=re.compile(r'结果|事实|证据|条件|范围|边界|限制|推断|建议|'
    r'\b(?:results?|facts?|evidence|conditions?|scope|boundaries|limitations?|inferences?|proposals?)\b',re.I)
_LIMIT=re.compile(r'条件|范围|边界|限制|\b(?:conditions?|scope|boundaries|limitations?)\b',re.I)


def enabled(record):
    return type(record.get('requestGroundingContractVersion')) is int and record['requestGroundingContractVersion']==3


def split_dimensions(part):
    from services.deep_research.evidence_requirements import _COMMAND,_outside_examples
    command=_COMMAND.match(part)
    if not command or not re.fullmatch(r'区分|distinguish',command.group(1),re.I): return None
    start=command.end();visible=_outside_examples(part)
    separators=list(re.finditer(r'[,，、]\s*(?:\band\b\s*)?|以及|和|与|\band\b',visible[start:],re.I))
    if not separators: return None
    spans=[]
    for match in separators:
        index=start+match.start();end=start+match.end()
        spans.append((index,end))
    labels=[];offset=start
    for index,end in spans:
        labels.append(part[offset:index].strip());offset=end
    labels.append(part[offset:].strip().rstrip('。.;；'))
    # An entity contrast (e.g. two method names or two metrics) needs its
    # relationship intact. Only named answer dimensions are independently due.
    if (not 2<=len(labels)<=4 or any(not 2<=len(label)<=120 or not _DIMENSION.search(_outside_examples(label))
                                    for label in labels)):
        return None
    return [{'requirement':label,'responseType':'limitation' if _LIMIT.search(label) else 'explanation'}
            for label in labels]


FINAL_DIMENSION_POLICY='''
Literal human deliverable dimensions are fixed separately in completionCriteria.
Audit EACH one against actual final accepted text/conditions, not just a related source
quote or an aggregate aspect. Missing any dimension leaves the obligation partial.
For checking/judging a claim, a numerical series alone is not an explicit qualified
judgement; do not require the reader to infer the conclusion. The visible answer must
state what the evidence supports and the bounds relevant to that judgement.
For reported results, applicable conditions and unverified scope, distinguish all three:
a known ablation failure is a reported result, not by itself an account of unverified
scope. Known parameter settings from one experiment do not supply another experiment's
conditions. An unverified-scope answer must explicitly bound what the obtained evidence
does not establish, without asserting paper-wide absence or inventing differences.
The same binding may support several dimensions only if its actual wording addresses
each. Source quotations can reveal missing conditions; they cannot stand in for omitted
answer prose. No keyword match or field identity is a semantic approval.
'''
