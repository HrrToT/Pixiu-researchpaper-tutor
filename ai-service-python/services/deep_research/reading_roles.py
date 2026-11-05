"""Rank substantive passages for literal request roles within the read cap.

These are navigation hints, never evidence support or a completeness verdict.
Each returned object is an unchanged, already source-eligible acquisition row.
"""
import re

from services.deep_research.obligation_binding import eligible_obligation_ids

_ASKS = (
    ('representation', r'表示|表征|基元|参数化|\brepresent\w*|\bprimitives?\b'),
    ('procedure', r'提取|融合|流程|步骤|重建路径|网格|\b(?:extract\w*|fus\w*|procedur\w*|pipeline|mesh)\b'),
    ('result', r'精度|质量|性能|数值|指标|耗时|速度|\b(?:results?|accurac\w*|quality|performance|metrics?|PSNR|SSIM|LPIPS|FPS|latency)\b'),
    ('settings', r'硬件|分辨率|评测条件|实验条件|数据集版本|\b(?:hardware|resolution|protocols?|evaluation settings|experimental settings)\b'),
    ('provenance', r'自报|同表|复现|重训|\b(?:provenance|reproduced?|retrained?|same.table|author.reported)\b'),
    ('resource', r'显存|存储|内存|\b(?:VRAM|memory|storage|model size)\b'),
)
_BODY = {
    'representation': r'\b(?:represent\w*|primitives?|parametri\w*|flatten\w*|compress\w*|ellipsoid\w*|covariance)\b|表示|表征|参数化|基元',
    'procedure': r'\b(?:extract\w*|fus\w*|integrat\w*|construct\w*|convert\w*|transform\w*)\b|提取|融合|构建|变换',
    'result': r'\b(?:Table|chamfer|PSNR|SSIM|LPIPS|FPS|latency|F1|accuracy|quantitative|evaluation|results?|time)\b|精度|质量|定量|耗时',
    'settings': r'\b(?:GPU|CPU|hardware|processors?|resolution|iterations?|protocol|experiments?|setup)\b|硬件|分辨率|实验设置',
    'provenance': r'\b(?:Table|caption|denot\w*|marked|re.train\w*|fine.tun\w*|baselines?|comparison)\b|表注|重训|复现',
    'resource': r'\b(?:VRAM|memory|storage|megabytes?|gigabytes?|model size)\b|显存|内存|存储',
}
_STOP = {'the','and','for','with','from','this','that','what','which','how','why','are','does',
         'paper','arxiv','http','https','org','psnr','ssim','lpips','fps','f1','gpu','cpu','vram'}
_REF_REQUEST = re.compile(r'参考文献|书目|\bbibliograph\w*|\b(?:references?|citations?)\s+(?:list|section)\b', re.I)


def _text(source):
    from services.deep_research.requested_measurements import _body
    # Normalize line wraps only in a ranking view. Returned source text stays exact.
    return re.sub(r'(?<=[A-Za-z])-[ \t]*\r?\n[ \t]*(?=[A-Za-z])', '', _body(source))


def quality(source, query=''):
    """Background/reference hints cannot override a literal bibliography request."""
    loc=source.get('location') or {}
    reference=(loc.get('sectionRole')=='references' or bool(re.search(
        r'\breferences?\b|\bbibliograph\w*', str(loc.get('section','')), re.I)))
    text=_text(source)
    expression=bool(re.search(r'[=＝≤≥<>]|\d+(?:\.\d+)?\s*(?:FPS|ms|GB|MB|%)\b',text,re.I))
    numeric_row=(len(re.findall(r'\d+\.\d+',text))>=3
                 and bool(re.search(r'\bTable\s+[IVX0-9]+',source.get('rankingContext',''),re.I)))
    tiny=(len(re.sub(r'\s+', '', text))<40 and not source.get('tableData')
          and not expression and not numeric_row and not _REF_REQUEST.search(query))
    return (not(reference and not _REF_REQUEST.search(query)), not tiny)


def _terms(query, sources):
    ignored=set(_STOP)
    for source in sources:
        title=str(source.get('title',''))
        label=title.split(':',1)[0]
        words=re.findall(r'[A-Za-z][A-Za-z0-9-]*', label)
        ignored.update(w.casefold() for w in words)
        if words:ignored.add(''.join(w[0] for w in words).casefold())
    return tuple(dict.fromkeys(w.casefold() for w in re.findall(
        r'\b[A-Za-z][A-Za-z0-9-]{1,}\b',query) if w.casefold() not in ignored))


def requests(obligations, sources):
    """Deduplicate role/source targets; retain literal benchmark terms separately."""
    result=[];seen=set()
    for oid, obligation in obligations.items():
        criteria=obligation.get('completionCriteria') or [{'requirement':obligation.get('question','')}]
        for criterion in criteria:
            query=criterion.get('requirement','')
            if not isinstance(query,str):continue
            for role,pattern in _ASKS:
                if not re.search(pattern,query,re.I):continue
                terms=_terms(query,sources) if role=='result' else ()
                # Later selection still checks source eligibility for each real oid.
                key=(role,terms,tuple(obligation.get('requiredSources') or ()))
                if key in seen:continue
                seen.add(key)
                result.append({'role':role,'terms':terms,'query':query,'obligationId':oid,
                               'criterionId':criterion.get('criterionId','whole_obligation')})
    return result


def score(source, request):
    text=_text(source);role=request['role'];matches=list(re.finditer(_BODY[role],text,re.I))
    if not matches and not (role=='result' and len(re.findall(r'\d+\.\d+',text))>=5
                            and re.search(r'\b(?:Table|Mean|PSNR|SSIM|LPIPS|F1)\b',source.get('rankingContext',''),re.I)):
        return 0
    own=bool(re.search(r'\b(?:we|our|this work)\b|本文|我们',text,re.I))
    numeric=bool(re.search(r'\d\.\d|\d+\s*(?:ms|min|hours?|FPS|GB|MB|%)\b',text,re.I))
    terms=request['terms'];context=source.get('rankingContext','')
    normalized=re.sub(r'[^a-z0-9]', '', (text+' '+context).casefold())
    hits=sum(re.sub(r'[^a-z0-9]', '', t) in normalized for t in terms)
    if terms and not hits:return 0
    loc=source.get('location') or {}
    method=loc.get('sectionRole')=='method' or bool(re.search(r'\bmethod|\bimplementation',str(loc.get('section','')),re.I))
    if role=='result':
        table=(len(re.findall(r'\d+\.\d+',text))>=5 and bool(re.search(
            r'\b(?:Table|Mean|PSNR|SSIM|LPIPS|F1)\b',text+' '+context,re.I)))
        direct=re.sub(r'[^a-z0-9]', '', text.casefold())
        direct_hits=sum(re.sub(r'[^a-z0-9]', '', t) in direct for t in terms)
        captions=re.findall(r'\bTable\s+[IVX0-9]+[.:]?\s*(?:Quantitative|Results|Evaluation|Comparison|Ablation)'
                            r'[^.!?]{0,350}',text+' '+context,re.I)
        caption_hits=sum(any(re.sub(r'[^a-z0-9]', '', t) in re.sub(r'[^a-z0-9]', '', c.casefold())
                             for c in captions) for t in terms)
        return 16*caption_hits+10*table+6*numeric+4*hits+8*direct_hits+min(3,len(matches))
    if role=='settings':
        platform=bool(re.search(r'\b(?:GPU|CPU|hardware|resolution|processors?)\b|硬件|分辨率',text,re.I))
        return 8*platform+2*numeric+min(3,len(matches))
    if role=='representation':
        parameterization=bool(re.search(r'[=＝Σ∑]|\b(?:parameteriz\w*|parametris\w*)\b',text,re.I))
        transformation=min(2,sum(bool(re.search(r'\b'+verb+r'\w*\b'
            r'[^.!?]{0,200}\b(?:scales?|axes|axis|matrix|dimensions?|parameters?|covariance|basis|tensor)\b',text,re.I))
            for verb in ('compress','flatten','project','transform')))
        return 5*transformation+3*parameterization+3*own+2*method+min(5,len(matches))
    if role=='procedure':
        stages=min(2,len(re.findall(r'\b(?:followed by|subsequently|post.training|then)\b|随后|然后',text,re.I)))
        authored=bool(re.search(r'\bwe\s+(?:\w+\s+){0,3}(?:extract\w*|fus\w*|construct\w*|'
            r'convert\w*|introduc\w*|develop\w*|render\w*|integrat\w*)\b',text,re.I))
        return 6*authored+4*stages+4*own+3*method+min(5,len(matches))
    return 2*own+2*numeric+min(4,len(matches))


def order(sources, obligations, fallback, *, extracted=()):
    """Balance requested roles/papers; novelty is not permission to read rubbish."""
    targets=requests(obligations,sources)
    identity=lambda s:(s.get('workId'),s.get('versionId'))
    works=list(dict.fromkeys(identity(s) for s in sources))
    extracted=set(extracted);queues=[]
    for request in targets:
        for work in works:
            own=[s for s in sources if identity(s)==work
                 and request['obligationId'] in eligible_obligation_ids(s,obligations)]
            ranked=sorted(own,key=lambda s:(quality(s,request['query']),score(s,request),
                (s['sourceId'],s.get('contentHash')) not in extracted),reverse=True)
            # A failed lexical match does not become a positive evidence claim.
            if ranked and quality(ranked[0],request['query'])==(True,True) and score(ranked[0],request)>0:
                queues.append(ranked)
    selected=[];seen=set()
    # A passage selected for two requested roles uses one slot. Do not consume
    # another slot merely because that same head already served an earlier role.
    for queue in queues:
        source=queue[0]
        if source['sourceId'] not in seen:
            selected.append(source);seen.add(source['sourceId'])
    query=' '.join(o.get('question','') for o in obligations.values())
    tail=sorted(fallback,key=lambda s:(quality(s,query),max((score(s,r) for r in targets),default=0),
        (s['sourceId'],s.get('contentHash')) not in extracted),reverse=True)
    while tail:
        counts={work:sum(identity(s)==work for s in selected) for work in works}
        best=min((s for s in tail if s['sourceId'] not in seen),
                 key=lambda s:counts[identity(s)],default=None)
        if best is None:break
        selected.append(best);seen.add(best['sourceId']);tail.remove(best)
    return selected


def premise_bundles(rows, obligations):
    """Carry request-role navigation into synthesis, not a new factual verdict.

    A full source passage can locate a benchmark heading while its unchanged
    quoted row carries values. This only ranks candidates; it never copies
    context from another source or replaces the independent ownership checks.
    """
    rows=[row for row in rows if row.get('verification',{}).get('literal')=='passed']
    sources=[{'title':row.get('sourceTitle','')} for row in rows]
    targets=requests(obligations,sources);chosen=[];seen=set();bundles=[];result_leads={}
    for request in targets:
        allowed=[e for e in rows if e.get('sourceWorkId') and request['obligationId'] in eligible_obligation_ids(
            {'workId':e.get('sourceWorkId'),'versionId':e.get('sourceVersionId'),
             'ownerMaterialId':e.get('ownerMaterialId')},obligations)]
        for work in dict.fromkeys((e['sourceWorkId'],e.get('sourceVersionId')) for e in allowed):
            own=[e for e in allowed if (e['sourceWorkId'],e.get('sourceVersionId'))==work]
            def view(row):
                context=row.get('sourceContext','')
                if not isinstance(context,str):context=''
                return {'text':row.get('quote',''),'location':row.get('location',{}),
                        'tableData':row.get('tableData'),'rankingContext':context}
            ranked=sorted(own,key=lambda e:(quality(view(e),request['query']),
                score(view(e),request),-len(e.get('quote',''))),reverse=True)
            # Generic author-report versus comparison-row provenance uses the
            # same requested result row. A separate ablation is not a substitute.
            # Explicit variant/marker questions still select actual caption prose.
            if request['role']=='provenance' and not re.search(r'重训|微调|标记|星号|\*|'
                    r'\bre.train\w*|\bfine.tun\w*|\bmark\w*|\bstar\w*',request['query'],re.I):
                shared=[e for e in result_leads.get(work,[]) if e in own]
                if shared:ranked=shared
            if request['role']=='result' and not request['terms'] and re.search(
                    r'核对|条件|方向|\b(?:settings?|conditions?|directions?)\b',request['query'],re.I):
                shared=[e for e in result_leads.get(work,[]) if e in own]
                if shared:ranked=shared
            if not ranked or quality(view(ranked[0]),request['query'])!=(True,True) or score(view(ranked[0]),request)<=0:
                continue
            lead=ranked[0]
            if request['role']=='result':result_leads.setdefault(work,[]).append(lead)
            group=[lead]
            def same_origin(e):
                return (all(e.get(k)==lead.get(k) for k in ('sourceId','sourceWorkId','sourceVersionId','contentHash','sourceContext'))
                        and isinstance(lead.get('sourceContext'),str) and bool(lead['sourceContext'])
                        and all((e.get('location') or {}).get(k)==(lead.get('location') or {}).get(k)
                                for k in ('page','offset','section')))
            if request['role']=='procedure' and re.match(
                    r'^\s*(?:Subsequently\b|Then\b|This\b|These\b|It\b|随后|然后|其中)',lead.get('quote',''),re.I):
                loc=lead.get('location') or {};start=loc.get('sourcePassageStart')
                prior=[e for e in own if e is not lead and type(start) is int and start>0
                    and same_origin(e)
                    and type((e.get('location') or {}).get('sourcePassageEnd')) is int
                    and e['location']['sourcePassageEnd']==start]
                if len(prior)==1:group=[prior[0],lead]
            elif request['role']=='result' and not re.search(r'\bTable\s+[IVX0-9]+',lead.get('quote',''),re.I):
                start=(lead.get('location') or {}).get('sourcePassageStart')
                captions=[e for e in own if e is not lead and same_origin(e)
                    and type(start) is int and type((e.get('location') or {}).get('sourcePassageEnd')) is int
                    and e['location']['sourcePassageEnd']<=start
                    and re.search(r'\bTable\s+[IVX0-9]+|\bQuantitative (?:comparison|results)',e.get('quote',''),re.I)]
                if captions:
                    caption=max(captions,key=lambda e:e['location']['sourcePassageEnd'])
                    group=[caption,lead]
            bundles.append({'obligationId':request['obligationId'],'criterionId':request['criterionId'],
                'requirement':request['query'],'source':lead['sourceVersionId'],
                'navigationRole':request['role'],'evidenceIds':[e['evidenceId'] for e in group]})
            for e in group:
                if e['evidenceId'] not in seen:chosen.append(e);seen.add(e['evidenceId'])
    return chosen,bundles
