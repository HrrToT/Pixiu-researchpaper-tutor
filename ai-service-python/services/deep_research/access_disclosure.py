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
    words=r'所依据|依据|提供|获取|取得|实际|阅读|读到|读了|材料|论文|内容|来源|本回答|本次|根据|判断|明确|说明|注明|标明|写明|全文|正文|摘要|片段|还是|是否|仅|只有|访问范围|阅读范围|获取范围|范围|并|是|为|的|了|到|或|和|及'
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


_PINNED_METHOD = re.compile(r'^(?:并|且)?引用\s*(?:(?:arXiv\s*[:：]\s*)?(\d{4}\.\d{4,5}v[1-9]\d*)|指定版本)\s*(?:的)?方法原文$', re.I)
_ABSENCE_NOTICE = re.compile(r'^若(?:未取得|未获取|找不到)正文[，,]?\s*(?:请)?(?:明确)?说明$')


def cited_access_version(criterion, obligation):
    """Recognize only access disclosure plus a pinned method citation."""
    if criterion.get('responseType') != 'identification':
        return None
    text = criterion.get('requirement', '')
    excerpt = obligation.get('requestExcerpt', '')
    sources = obligation.get('requiredSources', [])
    if (not isinstance(text, str) or not isinstance(excerpt, str) or not isinstance(sources, list)
            or len(sources) != 1 or not isinstance(sources[0], str)):
        return None
    text = re.sub(r'(若(?:未取得|未获取|找不到)正文)[，,]\s*(?=(?:请)?(?:明确)?说明)', r'\1', text)
    parts = [p.strip() for p in re.split(r'[。；;，,]', text) if p.strip()]
    access = [p for p in parts if access_only(p)]
    citations = [m for p in parts if (m := _PINNED_METHOD.fullmatch(p))]
    if (len(access) != 1 or len(citations) != 1
            or not any(access_only(p.strip()) for p in re.split(r'[。；;，,]', excerpt))
            or not re.fullmatch(r'arxiv:\d{4}\.\d{4,5}v[1-9]\d*', sources[0], re.I)
            or any(not (access_only(p) or _PINNED_METHOD.fullmatch(p) or _ABSENCE_NOTICE.fullmatch(p))
                   for p in parts)):
        return None
    version = sources[0].lower()
    return version if citations[0][1] is None or 'arxiv:' + citations[0][1].lower() == version else None


def cited_access_bindings_supported(bindings, known, metadata, version):
    from services.deep_research.display_metadata import display_binding_supported
    from services.deep_research.answer_coverage import _bindings_supported
    if not version or not isinstance(bindings, list) or not isinstance(metadata, dict):
        return False
    citations = metadata.get('pinnedMethodAccessRecords', {})
    labels = [b for b in bindings if isinstance(b, dict) and b.get('field') == 'sourceAccessSummary']
    prose = [b for b in bindings if b not in labels]
    return (bool(labels) and bool(prose) and _bindings_supported(prose, known)
            and all(display_binding_supported(b, known, metadata)
                    and any(citations.get(ref) == version for ref in known[b['claimId']].get('evidenceRefs', []))
                    and any(p['claimId'] == b['claimId'] for p in prose) for b in labels))


def access_requirements(plan,*,joint=False,citation_access=False,pinned_method_access=False):
    result={o['obligationId']:{'overall':True,'criteria':{
        c['criterionId'] for c in o.get('completionCriteria',[])
        if c.get('responseType')=='identification' and access_only(c.get('requirement'))}}
        for item in plan for o in item.get('obligations',[])
        if access_only(o.get('question'))}
    if joint:
        from services.deep_research.joint_answer_bindings import access_instruction
        for item in plan:
            for o in item.get('obligations',[]):
                if o['obligationId'] not in result and access_instruction(o.get('question',''),citation_access=citation_access):
                    result[o['obligationId']]={'overall':True,'criteria':set()}
    if pinned_method_access:
        for item in plan:
            for obligation in item.get('obligations', []):
                criteria = {c['criterionId'] for c in obligation.get('completionCriteria', [])
                            if cited_access_version(c, obligation)}
                if criteria:
                    scope = result.setdefault(obligation['obligationId'], {'overall': True, 'criteria': set()})
                    scope['criteria'].update(criteria)
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
