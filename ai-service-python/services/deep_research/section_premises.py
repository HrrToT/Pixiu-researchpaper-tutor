"""Keep explicitly requested sections inside already acquired literal evidence.

No new quote is assembled: a bundle contains separate, unchanged evidence units.
Only complete, non-overlapping acquired page fragments establish boundaries.
"""
from collections import Counter, defaultdict
import re

_REQUEST=re.compile(r'第\s*(\d+(?:\.\d+){0,3})\s*节|\b(?:section|sec\.)\s*(\d+(?:\.\d+){0,3})\b',re.I)
_HEADING=re.compile(r'(?m)^[ \t]*(\d+(?:\.\d+){0,3})[ \t]+(?=[A-Z\u4e00-\u9fff])')


def requested(question):
    from services.deep_research.evidence_requirements import _outside_examples
    result=[]
    for layer in getattr(question,'instruction_layers',(str(question),)):
        visible=_outside_examples(layer)
        for match in _REQUEST.finditer(visible):
            prefix=re.split(r'[。！？；，,\n]',visible[:match.start()])[-1]
            if re.search(r'不要|不用|无需|不必|别|do not|without',prefix,re.I):continue
            value=match.group(1) or match.group(2)
            if value not in result:result.append(value)
    return result


def priority_enabled(record):
    """Explicit section scope is independent of a mechanism-keyword heuristic.

    New immutable runs opt in. This only allocates existing literal evidence;
    it does not approve support or enlarge source, input or model budgets.
    """
    from services.deep_research.request_context import effective_question
    return (type(record.get('sectionPremisesContractVersion')) is int
            and record['sectionPremisesContractVersion']==1
            and record.get('state',{}).get('outputKind') in
                {'direction_survey','claim_verification','paper_comparison'}
            and bool(requested(effective_question(record))))


def explanation_only(record):
    """Do not turn a scoped explanation into a requested comparative verdict.

    Ambiguous or positive checking/comparison requests retain all old guidance.
    This affects drafting guidance only; verification gates remain unchanged.
    """
    from services.deep_research.request_context import effective_question
    from services.deep_research.evidence_requirements import _outside_examples
    question=effective_question(record)
    if not priority_enabled(record) or record.get('state',{}).get('outputKind')!='claim_verification':
        return False
    positives=[]
    for layer in getattr(question,'instruction_layers',(str(question),)):
        for clause in re.split(r'[，,;；。\n！？?!]|但是|不过|但|\bbut\b|\bhowever\b',_outside_examples(layer),flags=re.I):
            if not re.match(r'^\s*(?:(?:并且|并|且|也|请)\s*)?(?:不要|不用|无需|不必|别|do not|without)',clause,re.I):
                positives.append(clause)
    text=' '.join(positives)
    return (bool(re.search(r'解释|讲解|说明|为什么|为何|\b(?:explain|why|how|what)\b',text,re.I))
        and not re.search(r'比较|对比|核查|验证|检验|判断|评估|批判|质疑|优于|更好|优劣|多少|数值|定量|\b(?:compar\w*|check|verify|assess\w*|better|outperform\w*|claim|quantitative|values?|numbers?)\b',text,re.I))


def bundle(rows,read_sources,work,sections):
    """Return whole section units with exact same-page position provenance."""
    sources=defaultdict(list)
    sid_counts=Counter(s.get('sourceId') for s in read_sources)
    for source in read_sources:
        location=source.get('location',{});page=location.get('page');offset=location.get('offset')
        text=source.get('text');sid=source.get('sourceId')
        if (source.get('workId')!=work or source.get('ownerMaterialId')!=work
                or source.get('accessLevel')!='fulltext' or not source.get('versionId')
                or not source.get('contentHash') or not sid or sid_counts[sid]!=1
                or type(page) is not int or page<1 or type(offset) is not int or offset<0
                or not isinstance(text,str) or not text):continue
        sources[(source['versionId'],source['contentHash'],page)].append(source)
    candidates=[]
    for (version,content_hash,page),fragments in sources.items():
        fragments.sort(key=lambda s:s['location']['offset'])
        cursor=0;text='';valid=True
        for source in fragments:
            if source['location']['offset']!=cursor:valid=False;break
            text+=source['text'];cursor+=len(source['text'])
        if not valid:continue
        headings=list(_HEADING.finditer(text))
        for section in sections:
            starts=[h for h in headings if h.group(1)==section]
            if len(starts)!=1:continue
            start=starts[0].start()
            end=next((h.start() for h in headings if h.start()>start and not h.group(1).startswith(section+'.')),None)
            if end is None or not 0<end-start<=6000:continue
            intervals=[]
            for source in fragments:
                offset=source['location']['offset']
                for row in rows:
                    loc=row.get('location',{});a=loc.get('sourcePassageStart');b=loc.get('sourcePassageEnd')
                    if (row.get('sourceId')!=source['sourceId'] or row.get('sourceWorkId')!=work
                            or row.get('ownerMaterialId')!=work or row.get('sourceVersionId')!=version
                            or row.get('verification',{}).get('literal')!='passed'
                            or type(a) is not int or type(b) is not int
                            or not 0<=a<b<=len(source['text']) or source['text'][a:b]!=row.get('quote')):continue
                    if offset+b>start and offset+a<end and text[max(offset+a,start):min(offset+b,end)].strip():
                        intervals.append((offset+a,offset+b,row))
            intervals.sort(key=lambda item:item[0])
            if (not intervals or len(intervals)>10 or text[start:intervals[0][0]].strip() or text[intervals[-1][1]:end].strip()
                    or len({x[2]['evidenceId'] for x in intervals})!=len(intervals)
                    or any(a[1]>b[0] or text[a[1]:b[0]].strip() for a,b in zip(intervals,intervals[1:]))):continue
            candidates.append([x[2] for x in intervals])
    return min(candidates,key=lambda group:(len(group),sum(len(r['quote']) for r in group))) if candidates else []
