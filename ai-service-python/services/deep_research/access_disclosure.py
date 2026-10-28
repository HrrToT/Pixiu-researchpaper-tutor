"""Publication-owned acquisition labels, independent of paper findings."""
import re


def enabled(record):
    return (type(record.get('reportPresentationContractVersion')) is int
        and record['reportPresentationContractVersion']==4)


def access_only(text):
    """Conservative grammar for access identification, never mixed science."""
    if not isinstance(text,str):return False
    from services.deep_research.display_metadata import requests_access_level
    if not requests_access_level(text):return False
    words=r'所依据|依据|提供|获取|取得|实际|阅读|读到|读了|材料|论文|内容|来源|本回答|本次|根据|判断|明确|说明|标明|写明|全文|摘要|片段|还是|是否|仅|只有|访问范围|阅读范围|获取范围|范围|并|是|为|的|了|到|或|和|及'
    remainder=re.sub(words,'',text)
    return not re.sub(r'[\s，。？！、：；,.?!:;（）()“”"\-]','',remainder)


def access_bindings_supported(bindings,known,metadata,requirement):
    from services.deep_research.display_metadata import display_binding_supported
    if (not access_only(requirement) or not isinstance(metadata,dict)
            or type(metadata.get('taskSourceAccessContractVersion')) is not int
            or metadata['taskSourceAccessContractVersion']!=1
            or not isinstance(bindings,list) or not bindings):return False
    records=metadata.get('sourceAccessRecords',{})
    if not isinstance(records,dict):return False
    for binding in bindings:
        if not display_binding_supported(binding,known,metadata):return False
        refs=known[binding['claimId']].get('evidenceRefs',[])
        if not refs or any(records.get(ref) not in {'fulltext','abstract','user_note'} for ref in refs):return False
    return True


def access_requirements(plan,*,joint=False):
    result={o['obligationId']:{'overall':True,'criteria':{
        c['criterionId'] for c in o.get('completionCriteria',[])
        if c.get('responseType')=='identification' and access_only(c.get('requirement'))}}
        for item in plan for o in item.get('obligations',[])
        if access_only(o.get('question'))}
    if joint:
        from services.deep_research.joint_answer_bindings import access_instruction
        for item in plan:
            for o in item.get('obligations',[]):
                if o['obligationId'] not in result and access_instruction(o.get('question','')):
                    result[o['obligationId']]={'overall':True,'criteria':set()}
    return result


COVERAGE_GUIDANCE='''For a frozen obligation asking ONLY to identify fulltext/abstract
access, and its identification criteria asking ONLY that access question, bindings
may use {"claimId":"accepted citing claim ID","field":"sourceAccessSummary"}.
The exact server-rendered label is the answer, not scientific prose. Keep access
aspects with source_metadata basis tied to that claim's own supplied accessLevel.
Mixed methods/results/limitations criteria and original-question overall bindings
still require actual answer text/conditions. Never use access labels to answer science.'''


GUIDANCE='''The application displays source access separately from scientific claims:
for accepted citations from task papers or arXiv it derives a visible Chinese label
from their actual accessLevel (fulltext means FULLTEXT EXCERPTS, abstract means
ABSTRACT). This is acquisition metadata, never a paper finding or evidence that
the entire paper was read. Do not put access declarations in claim text/conditions
or assert "I read the entire paper". Fulfil methods/results with own original
quotations; leave explicit access-disclosure requirements to that server label.
Do not invent or change source access, add unrelated citations to obtain a label,
or treat access metadata as support for a scientific conclusion. If no accepted
citations provide a label, the access requirement remains unfinished.'''
