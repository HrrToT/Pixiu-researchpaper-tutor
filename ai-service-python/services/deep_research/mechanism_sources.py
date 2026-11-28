"""Human-grounded qualitative retrieval hints, never evidence approval."""
import re
from collections import Counter


_MECHANISM=re.compile(r'机制|原理|流程|哪些环节|怎样.{0,16}(?:减少|表示|编码)|\b(?:mechanisms?|pipelines?|how .{0,30}works?)\b',re.I)
_NUMERIC=re.compile(r'多少|数值|定量|量化对比|具体(?:大小|速度|结果)|单位|\b(?:FPS|PSNR|SSIM|LPIPS|latency|how many|how much|values?|numbers?|quantitative|measurements?)\b',re.I)
_NEGATIVE=re.compile(r'^\s*(?:(?:并且|并|且|也|请)\s*)?(?:不要|不用|无需|不必|不需|不得|别|do not|don.t|no need|without)',re.I)


def _positive(question):
    # Split contrast clauses so "不用公式但要数值" retains the numeric request.
    clauses=re.split(r'[，,;；。\n！？?!]|但是|不过|但|\bbut\b|\bhowever\b',str(question),flags=re.I)
    return ' '.join(c for c in clauses if not _NEGATIVE.search(c))


def qualitative(question):
    positive=_positive(question)
    return bool(_MECHANISM.search(positive) and not _NUMERIC.search(positive))


_MEASURE_SCOPE=re.compile(
    r'(?:列出|报告|给出|比较|对比|测量|评估|核对|明确).{0,80}?'
    r'(?:指标|数值|测量|结果|实验设置|存储与画质|画质取舍|渲染速度|存储大小|内存占用|帧率)'
    r'|\b(?:report|list|compare|measure|evaluate)\b.{0,100}?'
    r'\b(?:metrics?|results?|measurements?|settings?|memory|size|speed|quality)\b',re.I)


def _measurement_requirement(question):
    positive=_positive(question)
    return bool(_NUMERIC.search(positive) or _MEASURE_SCOPE.search(positive))


def _eligible(record):
    from services.deep_research.request_context import effective_question
    return (type(record.get('mechanismEvidenceContractVersion')) is int
        and record['mechanismEvidenceContractVersion'] in (1,2,3,4)
        and record.get('state',{}).get('outputKind') in {'direction_survey','claim_verification','paper_comparison'}
        and qualitative(effective_question(record)))


def enabled(record):
    from services.deep_research.request_context import effective_question
    return (_eligible(record) and not (record['mechanismEvidenceContractVersion']==4
        and _measurement_requirement(effective_question(record))))


def for_query(record,query,owned_id):
    if not _eligible(record):return False
    from services.deep_research.criterion_sources import acquisition_questions
    questions=acquisition_questions(record,query,owned_id)
    if record['mechanismEvidenceContractVersion']==4:
        # One mechanism clause must not suppress metric tables for a different,
        # source-bound measurement obligation. Model query words alone never
        # opt a qualitative user request into numeric retrieval.
        return bool(questions) and not any(_measurement_requirement(q) for q in questions)
    return bool(questions)


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


def comparison_mechanism(obligation):
    role = obligation.get('comparisonRole') or {}
    return (role.get('kind') == 'per_paper'
            and bool(_MECHANISM.search(role.get('requestExcerpt', '')))
            and not any(_measurement_requirement(criterion['requirement'])
                        for criterion in obligation.get('completionCriteria', [])))


def representation_requested(text):
    return bool(re.search(r'表示|\brepresentation\b', text, re.I))


def representation_sentences(text):
    """Locate complete parameter definitions, retaining original offsets."""
    from services.deep_research.quote_context import _sentence_cuts

    start = 0
    for end in _sentence_cuts(text):
        sentence = ' '.join(text[start:end].split())
        if 30 <= len(sentence) <= 650 and re.search(
                r'\b(?:coefficients?|parameters?|embeddings?)\b[^.!?]{0,60}\b(?:represent(?:s|ing)?|encode[sd]?|encoding)\b'
                r'|\b(?:defined|parameterized|represented|encoded) (?:by|with|through)\b[^.!?]{0,60}'
                r'\b(?:coefficients?|parameters?|embeddings?)\b', sentence, re.I):
            yield int(bool(re.search(r'view[- ]dependent|color|appearance|geometry|radiance', sentence, re.I))), start, end
        start = end


def representation_read_requested(record, query, pdf_id):
    from services.deep_research.criterion_sources import acquisition_questions

    version = record.get('comparisonPaperWordingContractVersion')
    return (type(version) is int and version in (2, 3, 4)
            and any(representation_requested(question)
                    for question in acquisition_questions(record, query, pdf_id)))


def include_pdf_representation(rows, pages, material, limit):
    """Use one existing retrieval slot for a complete owned PDF sentence."""
    from services.deep_research.contracts import digest

    replace = next((i for i in range(len(rows) - 1, 0, -1) if not rows[i].get('tableData')
                    and rows[i].get('retrievalMode') in (None, 'pdf_lexical_fallback', 'indexed_hybrid')), None)
    if len(rows) >= limit and replace is None:
        return rows
    best = None
    for page in pages:
        for score, start, end in representation_sentences(page.get('text', '')):
            priority = (score, -(end - start))
            if best is None or priority > best[0]:
                best = (priority, page, start, end)
    if best is None:
        return rows
    _, page, start, end = best
    quote = page['text'][start:end]
    owner = material['materialId']
    content_hash = material['contentHash']
    location = {'page': page['page'], 'pageIndex': page['page'] - 1, 'pageResolution': 'exact',
                'offset': start, 'matchedRepresentationDefinition': True}
    candidate = {'sourceId': 'src_' + digest([owner, content_hash, location, quote]), 'pdfId': owner,
                 'contentHash': content_hash, 'versionId': material.get('versionId') or content_hash,
                 'title': material.get('title', owner), 'text': quote, 'location': location,
                 'accessLevel': 'fulltext', 'retrievalMode': 'pdf_representation_definition'}
    if any(row['sourceId'] == candidate['sourceId'] for row in rows):
        return rows
    result = list(rows)
    if len(result) < limit:
        result.append(candidate)
    else:
        result[replace] = candidate
    return result


def compression_mapping_requested(text, *, include_operations=False):
    positive = _positive(text)
    return bool(re.search(r'压缩机制|压缩原理|压缩后.{0,12}表示|'
                          r'\bcompression mechanisms?\b|\bcompressed (?:deployment )?representation\b',
                          positive, re.I)
                or include_operations and re.search(r'压缩(?:或优化)?操作', positive))


def compression_mapping_score(text, section):
    """Find an authored mapping from source features to a compact codebook."""
    if re.search(r'related work|bibliography|references|^table\b', section.strip(), re.I):
        return 0
    text = ' '.join(text.split())
    if not (re.search(r'\b(?:we|our)\b', text, re.I)
            and re.search(r'\b(?:codebooks?|code vectors?|codes)\b', text, re.I)):
        return 0
    if re.search(r'\b(?:assign\w*|associat\w*|map\w*|group\w*|segment\w*|quantiz\w*|cluster\w*)\b[^.!?]{0,165}'
                 r'\b(?:to the (?:closest|nearest|K) codes?|closest code|codebook mapping)\b', text, re.I):
        return 3
    if re.search(r'\b(?:gaussian|feature|vector)[-\s]+to[-\s]+codebook mapping\b', text, re.I):
        return 2
    return 0


def distillation_operation_score(text, section):
    """Rank the teacher-to-student signal and the construction of training views."""
    if re.search(r'related work|background|bibliography|references|^table\b', section.strip(), re.I):
        return 0
    text = ' '.join(text.split())
    learner = r'(?:models?|networks?|classifiers?)\b'
    teacher_student = re.search(rf'\bteacher {learner}.{{0,200}}\bstudent {learner}'
                                rf'|\bstudent {learner}.{{0,200}}\bteacher {learner}', text, re.I)
    signal = re.search(r'\b(?:supervis\w*|loss|match\w*|differences?)\b', text, re.I)
    if not (teacher_student and signal):
        return 0
    synthesized_views = re.search(r'\b(?:pseudo[\s‐‑–-]*views?|novel views?)\b|\btpseudo\b', text, re.I)
    camera_change = re.search(r'\b(?:camera (?:pose|position|rotation|translation)|perturb\w*|jitter\w*)\b', text, re.I)
    return 3 + 2 * bool(synthesized_views and camera_change)


def pruning_recovery_score(text, section):
    """Find a direct link from pruning or removal to a recovery operation."""
    if re.search(r'related work|background|bibliography|references|^table\b', section.strip(), re.I):
        return 0
    for sentence in re.split(r'[.!?。！？]+', ' '.join(text.split())):
        if (re.search(r'\b(?:prun\w*|remov\w*)\b|剪枝|剔除', sentence, re.I)
                and re.search(r'\brecover\w*\b|\bfinetun\w*\b|\bfine[ -]tun\w*\b|'
                              r'\bco[ -]adapt\w*\b|恢复|微调', sentence, re.I)):
            return 1
    return 0


def comparison_overviews(sources, obligations, extracted, *, compression_operations=False):
    from services.deep_research.obligation_binding import eligible_obligation_ids

    active = {oid: obligation for oid, obligation in obligations.items() if comparison_mechanism(obligation)}
    best = {}
    distillation = {}
    for source in sources:
        identity = (source.get('workId'), source.get('versionId'))
        if (source.get('accessLevel') != 'fulltext' or source.get('tableData') or not all(identity)
                or source.get('ownerMaterialId') != identity[0]
                or (source['sourceId'], source.get('contentHash')) in extracted
                or not set(source.get('obligationIds', [])).intersection(eligible_obligation_ids(source, active))):
            continue
        text = source.get('text', '')
        section = source.get('location', {}).get('section', '')
        score = overview_score(text, section)
        if compression_operations and any(
            compression_mapping_requested(c['requirement'], include_operations=compression_operations in (3, 4, 5, 6))
            for oid in eligible_obligation_ids(source, active)
            for c in active[oid].get('completionCriteria', [])
        ):
            score += 100 * compression_mapping_score(text, section)
        if score > best.get(identity, (0, None))[0]:
            best[identity] = (score, source)
        if compression_operations in (4, 5, 6):
            from services.deep_research.method_intent import query_intents
            if any('distillation_operation' in query_intents(question, compression_operations=4)
                   for oid in eligible_obligation_ids(source, active)
                   for question in [active[oid]['question'],
                                    *(c['requirement'] for c in active[oid].get('completionCriteria', []))]):
                detail = distillation_operation_score(text, section)
                if detail > distillation.get(identity, (0, None))[0]:
                    distillation[identity] = (detail, source)
    selected = {source['sourceId']: source for _, source in (*distillation.values(), *best.values())}
    return list(selected.values())


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


def component_bundle(rows, read_sources, work, *, allow_pipeline=False):
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
        if marker is None and allow_pipeline:
            marker=re.search(r'\b(?:our|the|a) (?:[a-z]+ )?pipeline\s*[:：]|(?:整体|总体)流程\s*[:：]',text,re.I)
        if not marker:continue
        suffix=text[marker.start():]
        heading=re.search(r'\n\s*(?:\d+\.?\s+[A-Z]|Related Work\b|Experiments\b'
                          + (r'|In summary\b|总结而言' if allow_pipeline else '') + ')',suffix)
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
