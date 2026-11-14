"""Human-grounded qualitative retrieval hints, never evidence approval."""
import re
from collections import Counter


_MECHANISM=re.compile(r'机制|原理|流程|哪些环节|怎样.{0,16}(?:减少|表示|编码)|\b(?:mechanisms?|pipelines?|how .{0,30}works?)\b',re.I)
_NUMERIC=re.compile(r'多少|数值|定量|量化对比|具体(?:大小|速度|结果)|单位|\b(?:FPS|PSNR|SSIM|LPIPS|latency|how many|how much|values?|numbers?|quantitative|measurements?)\b',re.I)
_NEGATIVE=re.compile(r'^\s*(?:(?:并且|并|且|也|请)\s*)?(?:不要|不用|无需|不必|不需|不得|别|do not|don.t|no need|without)',re.I)


def qualitative(question):
    # Split contrast clauses so "不用公式但要数值" retains the numeric request.
    clauses=re.split(r'[，,;；。\n！？?!]|但是|不过|但|\bbut\b|\bhowever\b',str(question),flags=re.I)
    positive=' '.join(c for c in clauses if not _NEGATIVE.search(c))
    return bool(_MECHANISM.search(positive) and not _NUMERIC.search(positive))


def enabled(record):
    from services.deep_research.request_context import effective_question
    return (type(record.get('mechanismEvidenceContractVersion')) is int
        and record['mechanismEvidenceContractVersion'] in (1,2,3)
        and record.get('state',{}).get('outputKind') in {'direction_survey','claim_verification','paper_comparison'}
        and qualitative(effective_question(record)))


def for_query(record,query,owned_id):
    if not enabled(record):return False
    from services.deep_research.criterion_sources import acquisition_questions
    return bool(acquisition_questions(record,query,owned_id))


def overview_score(text,section):
    section=str(section);body=re.split(r'\bContent:\s*',str(text),maxsplit=1)[-1]
    if re.search(r'related work|background|references|bibliography|ablation|appendix|supplement|\b(?:experiments?|results?|evaluation|table)\b|相关工作|参考文献',section,re.I):return 0
    if body.lstrip().startswith('Table caption:'):return 0
    main=bool(re.match(r'^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?(?:methods?\b|proposed\s+(?:method|approach)|overview\b|approach\b|pipeline\b|方法|总体)',section,re.I))
    pipeline=bool(re.search(r'\b(?:pipeline|overview|overall (?:method|framework|approach)|consists? of)\b|整体流程|总体方法',body,re.I))
    contributions=(len(re.findall(r'•|(?:^|\n)\s*[-*]',body))>=2 and bool(re.search(r'\b(?:our|contributions?|novel elements|to sum up)\b',body,re.I)))
    own=bool(re.search(r'\b(?:we|our|this work)\b|本文|我们',body,re.I))
    introduction=bool(re.search(r'\b(?:introduc|propos|process|encod|prun|quantiz|distill|reduc)\w*',body,re.I))
    return 20*main+6*pipeline+25*contributions+2*own+introduction if main or pipeline or contributions else 0


def prefer_sources(indexed,candidates,record,query,owned_id,limit):
    """Reserve at most two existing slots for intact owned method passages."""
    selected=list(indexed[:limit])
    if not selected or limit<2 or not for_query(record,query,owned_id):return selected
    meta=selected[0].get('metadata') or {};version=meta.get('index_version')
    if selected[0].get('pdfId')!=owned_id or meta.get('id')!=owned_id or not isinstance(version,str) or not re.fullmatch('[0-9a-f]{16}',version):return selected
    own=[r for r in candidates if r.get('pdfId')==owned_id and (r.get('metadata') or {}).get('id')==owned_id
        and r['metadata'].get('index_version')==version and type(r['metadata'].get('chunk_index')) is int
        and r.get('sourceId')==f"{owned_id}-v{version}-chunk-{r['metadata']['chunk_index']}"
        and r.get('accessLevel','fulltext')=='fulltext']
    ids=Counter(r['sourceId'] for r in own);chunks=Counter(r['metadata']['chunk_index'] for r in own)
    own=[r for r in own if ids[r['sourceId']]==1 and chunks[r['metadata']['chunk_index']]==1]
    ranked=sorted(own,key=lambda r:(-overview_score(r.get('text',''),r['metadata'].get('section_title','')),r['metadata']['chunk_index']))
    primary=[r for r in ranked if overview_score(r.get('text',''),r['metadata'].get('section_title',''))>0][:min(2,limit-1)]
    chosen=[];seen=set()
    for r in [*primary,*selected]:
        if r['sourceId'] not in seen:chosen.append(r);seen.add(r['sourceId'])
    return chosen[:limit]


def component_bundle(rows, read_sources, work):
    """Keep a visible authored component list intact across literal passage units.

    Units remain separate original evidence. No new quote, identity or support
    verdict is created; the existing input fitter must admit the whole bundle.
    """
    bundles=[]
    counts=Counter(s.get('sourceId') for s in read_sources)
    for source in read_sources:
        sid=source.get('sourceId');text=source.get('text')
        if (not sid or counts[sid]!=1 or source.get('workId')!=work
                or source.get('ownerMaterialId')!=work or not source.get('versionId')
                or source.get('accessLevel')!='fulltext' or not isinstance(text,str)):
            continue
        section=source.get('location',{}).get('section','')
        if re.search(r'related work|background|references|ablation|appendix|experiment|result',section,re.I):
            continue
        marker=re.search(r'\b(?:our contributions? (?:include|are)|to sum up.{0,30}contributions?)\b|本文的?贡献(?:包括|如下)',text,re.I)
        if not marker:continue
        suffix=text[marker.start():]
        heading=re.search(r'\n\s*(?:\d+\.?\s+[A-Z]|Related Work\b|Experiments\b)',suffix)
        end=marker.start()+heading.start() if heading else len(text)
        block=text[marker.start():end]
        if len(block)>1800 or len(re.findall(r'•|(?:^|\n)\s*[-*]',block))<2:continue
        units=[]
        for row in rows:
            location=row.get('location',{});start=location.get('sourcePassageStart');stop=location.get('sourcePassageEnd')
            if (row.get('sourceId')!=sid or row.get('sourceWorkId')!=work
                    or row.get('ownerMaterialId')!=work or row.get('sourceVersionId')!=source['versionId']
                    or row.get('verification',{}).get('literal')!='passed'
                    or type(start) is not int or type(stop) is not int
                    or not 0<=start<stop<=len(text) or text[start:stop]!=row.get('quote')):
                continue
            if stop>marker.start() and start<end:units.append(row)
        units.sort(key=lambda r:r['location']['sourcePassageStart'])
        if (not units or len(units)>3 or len({r['evidenceId'] for r in units})!=len(units)
                or units[0]['location']['sourcePassageStart']>marker.start()
                or units[-1]['location']['sourcePassageEnd']<end
                or any(a['location']['sourcePassageEnd']!=b['location']['sourcePassageStart'] for a,b in zip(units,units[1:]))):
            continue
        bundles.append(units)
    return min(bundles,key=lambda b:(len(b),sum(len(r['quote']) for r in b))) if bundles else []
