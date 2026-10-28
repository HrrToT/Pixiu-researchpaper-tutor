"""Compact prose for a human-bounded factual check, not a scientific shortcut."""

def enabled(record,kind,limit):
    return (type(record.get('answerFormatContractVersion')) is int
        and record['answerFormatContractVersion'] in (2,3) and kind=='claim_verification'
        and type(limit) is int and 0<limit<=300)


PROSE_GUIDANCE="""
Short factual-check layout: distribute the requested aspects across the answer points,
not five mini-reports inside every point. Use ordinary concise Chinese paragraphs.
Do not repeat 判断/支持证据/反对证据/适用条件/未解决事项 labels in every text unless
explicitly requested by the human. Section headings are layout, not text to copy.
Lead with the bounded assessment and the minimum evidence needed to interpret it;
put relevant evaluated settings and the stronger unsupported inference beside it or
in the other requested point. Preserve all actual requested distinctions jointly.
Use only necessary numerical examples, not whole rows or repeated metric inventories.
Every retained number still needs its method, group, metric and exact source identity.
Do not invent opposing evidence, a tolerance, or paper-wide missing experiments to
fill a report label. Briefness never permits dropping necessary conditions or mechanisms.
"""

ACCESS_GUIDANCE="""detailLevel means source access: use ONLY fulltext or abstract, not summary/brief.
An abstract-only source remains abstract; a short answer does not change access level.
"""


GUIDANCE=PROSE_GUIDANCE+ACCESS_GUIDANCE

def valid_access_labels(claims):
    return isinstance(claims,list) and all(isinstance(c,dict)
        and isinstance(c.get('detailLevel'),str) and c['detailLevel'] in {'fulltext','abstract'} for c in claims)


def joint_compaction(record,kind,limit):
    return enabled(record,kind,limit) and record['answerFormatContractVersion']==3
