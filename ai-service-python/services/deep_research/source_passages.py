"""Save original read passages without model transcription or semantic approval."""
from copy import deepcopy
import re
from time import monotonic

from services.deep_research.contracts import DeepResearchError, digest
from services.deep_research.obligation_binding import eligible_obligation_ids
from services.deep_research.table_evidence import attach_table_packet, visible_table_packet

MAX_PASSAGE_BYTES = 3000
MAX_UNITS = 1024
WRAPPER = re.compile(r'^Paper: (?P<title>[^\n]*)\n\nSection: (?P<section>[^\n]*)\n\nContent:\n', re.DOTALL)
OWNED = ('evidenceId','sourceWorkId','sourceVersionId','contentHash','accessLevel','quote',
    'location','sourceContext','sourceQuoteStart','sourceContextStart','conditions','sourceId','sourceKind','sourceTitle',
    'sourceUrl','ownerMaterialId','sourcePublicationIdentity','extractionKind','tableData')


def enabled(record):
    return (type(record.get('adaptiveExtractionContractVersion')) is int
        and record['adaptiveExtractionContractVersion'] in (2,3))


def _byte_spans(text, limit):
    """Partition an oversized sentence group at existing whitespace if possible."""
    start = 0
    while start < len(text):
        end = start; size = 0; boundary = None
        while end < len(text) and size + len(text[end].encode('utf8')) <= limit:
            size += len(text[end].encode('utf8')); end += 1
            if text[end-1].isspace() and size >= limit // 2: boundary = end
        if end == start: raise ValueError('Passage byte limit is too small')
        if end < len(text) and boundary is not None: end = boundary
        yield start, end
        start = end


def spans(text, limit=MAX_PASSAGE_BYTES):
    """Keep every character in contiguous groups of at most three sentences.

    Long groups receive a further byte-safe partition. Segmentation is not a
    relevance judgement; original occurrence/context remains attached to each.
    """
    from services.deep_research.quote_context import _sentence_cuts
    ends = _sentence_cuts(text)[2::3]
    if ends and not text[ends[-1]:].strip(): ends[-1] = len(text)
    if not ends or ends[-1] != len(text): ends.append(len(text))
    start = 0
    for end in ends:
        for a,b in _byte_spans(text[start:end], limit): yield start+a, start+b
        start = end


def _keep_local_method_passage(record, source, location, body):
    version = record.get('localSectionContextContractVersion')
    limit = 1800 if version == 9 and location.get('matchedPdfRunInHeading') else 1500
    if (version not in (7, 8, 9) or len(record.get('materials', ())) != 1
            or location.get('matchedPdfMethodPassage') is not True or location.get('sectionRole') != 'method'
            or source.get('accessLevel') != 'fulltext' or source.get('tableData')
            or len(source.get('pages', ())) != 1 or not body.strip() or len(body) > limit
            or len(body.encode('utf8')) > MAX_PASSAGE_BYTES or body != source.get('text')):
        return False
    material, = record['materials']
    owner = material.get('materialId')
    content_hash = material.get('contentHash')
    version = material.get('versionId') or content_hash
    return bool(owner and content_hash and source.get('ownerMaterialId') == source.get('workId') == owner
                and source.get('versionId') == version and source.get('contentHash') == content_hash)


def body_start(source, location, text, *, owned_title=None):
    prefix = f"Paper: {source.get('title')}\n\nSection: {location.get('section')}\n\nContent:\n"
    if text.startswith(prefix): return len(prefix)
    if owned_title is not None:
        owned_prefix=f"Paper: {owned_title}\n\nSection: {location.get('section')}\n\nContent:\n"
        if text.startswith(owned_prefix):return len(owned_prefix)
    match = WRAPPER.match(text)
    if match:
        if (match['title'] != source.get('title') and (owned_title is None or match['title'] != owned_title)
                or match['section'] != location.get('section')):
            raise DeepResearchError('invalid_source_passage','读取片段的正文包装与来源信息不一致，未提取证据。')
        return match.end()
    return 0



def owned_wrapper_title(record,source):
    """An exact snapshot-bound material ID, never a fuzzy display-title alias.

    Indexed passage hashes differ from original PDF hashes. Bind the wrapper to
    the immutable material snapshot/version, not to the passage's contentHash.
    """
    if (type(record.get('sourceWrapperIdentityContractVersion')) is not int
        or record['sourceWrapperIdentityContractVersion']!=1 or source.get('sourceKind')!='task_paper'):
        return None
    work=source.get('workId')
    if not isinstance(work,str) or not work or source.get('ownerMaterialId')!=work:return None
    material=next((m for m in record.get('materials',[]) if m.get('materialId')==work),None)
    if not material or material.get('workId',work)!=work:return None
    sha=material.get('contentHash')
    if not isinstance(sha,str) or not re.fullmatch(r'[a-f0-9]{64}',sha):return None
    if work!=sha+'.pdf' or source.get('versionId')!=(material.get('versionId') or sha):return None
    return work


def projection(evidence, *, literal_state=False):
    result={key:deepcopy(evidence[key]) for key in OWNED if key in evidence}
    if literal_state:
        result['literalVerification']=evidence.get('verification',{}).get('literal')
        if 'textQualityAudit' in evidence:result['textQualityAudit']=deepcopy(evidence['textQualityAudit'])
    return result


def extract(record, make_evidence, validate, update):
    from contextlib import nullcontext
    batch = getattr(make_evidence, '__dict__', {}).get('physical_page_batch')
    use_batch = callable(batch)
    with batch() if use_batch else nullcontext():
        return _extract(record, make_evidence, validate, update, recheck_scope=use_batch)


def _extract(record, make_evidence, validate, update, *, recheck_scope=False):
    extraction_started=monotonic()
    run_id = record['runId']; state = record.get('state', {})
    canonical = record['adaptiveExtractionContractVersion'] == 3
    input_version = 2 if canonical else 1
    from services.deep_research.source_passage_reuse import rejected_state_enabled
    from services.deep_research.text_quality import literal_state_valid
    rejected_states=rejected_state_enabled(record)
    frozen_projection=lambda ev:projection(ev,literal_state=rejected_states)
    sources = state.get('readResults', [])
    from services.deep_research import experiment_protocol_sources as protocol
    continuations = protocol.continuation_spans(sources) if protocol.enabled(record) else set()
    densification = protocol.densification_enabled(record)
    keep_benchmark_protocol = record.get('comparisonNamedBenchmarkProtocolVersion') in (1, 2)
    if keep_benchmark_protocol:
        from services.deep_research.pdf_benchmark_protocol import owned_protocol
    obligations = {o['obligationId']:o for p in state.get('plan', []) for o in p['obligations']}
    old_evidence = state.get('evidence', [])
    evidence = deepcopy(old_evidence); by_id = {e['evidenceId']:e for e in evidence}
    journal = deepcopy(state.get('sourcePassageExtraction', {'version':1,'entries':{}}))
    if (len(by_id) != len(evidence) or not isinstance(journal,dict) or set(journal) != {'version','entries'}
            or type(journal['version']) is not int or journal['version'] != 1 or not isinstance(journal['entries'],dict)):
        raise DeepResearchError('invalid_source_passage_state','保存的原文证据状态无效，不能继续提取。')
    for key, entry in journal['entries'].items():
        if (not isinstance(entry,dict) or set(entry) != {'input','evidenceId','evidenceDigest'}
                or not isinstance(entry['input'],dict)
                or set(entry['input']) != {'version','sourceId','workId','versionId','contentHash','accessLevel',
                    'location','originalTextDigest','quote','obligations'}
                or type(entry['input']['version']) is not int or entry['input']['version'] != input_version
                or key != digest(entry['input']) or entry['evidenceId'] not in by_id
                or entry['evidenceDigest'] != digest(frozen_projection(by_id[entry['evidenceId']]))):
            raise DeepResearchError('invalid_source_passage_state','保存的原文证据或输入摘要已改变，不能继续提取。')
        old = by_id[entry['evidenceId']]; frozen = entry['input']
        literal=old.get('verification',{}).get('literal')
        if ((literal not in ('passed','failed') if rejected_states else literal!='passed')
                or rejected_states and not literal_state_valid(old)
                or any(frozen[a] != old.get(b) for a,b in (('sourceId','sourceId'),('workId','sourceWorkId'),
                    ('versionId','sourceVersionId'),('contentHash','contentHash'),('accessLevel','accessLevel'),
                    ('quote','quote')))
                or frozen['originalTextDigest'] != digest(old.get('sourceContext'))):
            raise DeepResearchError('invalid_source_passage_state','保存的原文证据与来源身份不一致。')
        if canonical:
            from services.deep_research.quote_pages import resolve_quote_location
            # The factory may resolve/remove positional hints. Other locator
            # fields, including original passage offsets, must remain exact.
            same_location = (resolve_quote_location('',[],frozen['location'])
                == resolve_quote_location('',[],old.get('location')))
        else:
            same_location = frozen['location'] == old.get('location')
        if not same_location:
            raise DeepResearchError('invalid_source_passage_state','原始片段与规范定位的非页码身份不一致。')
    from services.deep_research.source_passage_reuse import enabled as reuse_enabled,key as reuse_key,register,same_metadata
    reusable={}
    reuse_literals=reuse_enabled(record)
    if reuse_literals:
        for entry in journal['entries'].values():register(reusable,entry)
    batch_scope = callable(getattr(type(validate), 'validate_materials', None))
    if batch_scope and not validate.validate_materials(run_id, list(dict.fromkeys(s['workId'] for s in sources))):
        raise DeepResearchError('scope_revoked','材料范围核对未通过，尚未提取原文证据。')
    units = 0
    created_quotes = 0
    for source in sources:
        if not batch_scope and not validate(run_id, source['workId']):
            raise DeepResearchError('scope_revoked','材料范围核对未通过，尚未提取原文证据。')
        eligible = eligible_obligation_ids(source, obligations)
        if not eligible or source.get('accessLevel') not in ('fulltext','abstract','user_note'): continue
        identity = {k:source[k] for k in ('workId','versionId','contentHash','accessLevel')}
        for page in source.get('pages', []):
            text = page.get('text', '')
            if not isinstance(text,str): raise DeepResearchError('invalid_source_passage','读取正文不是文本，未提取证据。')
            location = {**source.get('location', {}), **{k:v for k,v in page.items() if k != 'text'}}
            offset = body_start(source, location, text, owned_title=owned_wrapper_title(record,source))
            body = text[offset:]
            # A short same-page method passage can support a sequence of
            # operations under one literal citation, including its final step.
            keep_whole = _keep_local_method_passage(record, source, location, body) or (
                keep_benchmark_protocol and owned_protocol(source, location, body, record.get('materials', ())))
            if (record.get(protocol.BASELINE_CONFIG_MARKER) == 2 and source['accessLevel'] == 'fulltext'
                    and source.get('ownerMaterialId') == source.get('workId')
                    and location.get('baselineEvaluationPart') in (protocol.BASELINE_SPLIT, protocol.BASELINE_TASKS)
                    and body == source.get('text') and len(body.encode('utf8')) <= MAX_PASSAGE_BYTES):
                keep_whole = True
            ranges = [(0, len(body))] if keep_whole else list(spans(body))
            if record.get('comparisonMechanismReadContractVersion') in (4, 5, 6) and source['accessLevel'] == 'fulltext':
                from services.deep_research.criterion_sources import criterion_targets
                from services.deep_research.mechanism_sources import distillation_operation_score

                if any(intent == 'distillation_operation' for _, _, intent in criterion_targets(
                        {oid: obligations[oid] for oid in eligible}, compression_operations=4)):
                    section = location.get('section') or ''
                    score = distillation_operation_score(body, section)
                    if score and not any(distillation_operation_score(body[a:b], section) == score for a, b in ranges):
                        combined = [(a, b) for (a, _), (_, b) in zip(ranges, ranges[1:])
                                    if len(body[a:b].encode('utf8')) <= MAX_PASSAGE_BYTES
                                    and distillation_operation_score(body[a:b], section) == score]
                        if combined:
                            ranges.append(min(combined, key=lambda span: span[1] - span[0]))
            if source['sourceId'] in continuations:
                original_span = protocol.continuation_range(body)
                if original_span and not any(a <= original_span[0] and original_span[1] <= b for a, b in ranges):
                    ranges.append(original_span)
            if densification and source['accessLevel'] == 'fulltext' and any(
                    protocol.DENSIFICATION in protocol.roles(obligations[oid], densification=True) for oid in eligible):
                original_span = protocol.densification_range(body)
                if original_span and not any(a <= original_span[0] and original_span[1] <= b for a, b in ranges):
                    ranges.append(original_span)
            packet = visible_table_packet(source.get('tableData'), body)
            # Preserve a parser-established row atomically if a prose boundary
            # would divide it. Never reconstruct cells from partial text.
            for number, method, values in packet['rows'] if packet else []:
                literal = f'Table row {number}: ' + ' | '.join([method, *values])
                first = body.index(literal); last = first + len(literal)
                if not any(a <= first and last <= b for a,b in ranges): ranges.append((first,last))
            for first, last in ranges:
                start, end = offset + first, offset + last
                quote = text[start:end]
                if not quote.strip(): continue
                units += 1
                if units > MAX_UNITS:
                    raise DeepResearchError('source_passage_capacity','本次读取的原文片段超过保存上限，原始资料保留，尚未完成提取。')
                loc = {**location, 'sourcePassageStart':start, 'sourcePassageEnd':end}
                frozen = {'version':input_version,'sourceId':source['sourceId'], **identity,
                    'location':loc,'originalTextDigest':digest(text),'quote':quote,
                    'obligations':[{k:obligations[oid][k] for k in ('obligationId','question','requiredSources','completionCriteria')
                        if k in obligations[oid]} for oid in eligible]}
                key = digest(frozen)
                if canonical and key in journal['entries']:
                    old = by_id[journal['entries'][key]['evidenceId']]
                    old['obligationIds'] = list(dict.fromkeys([*old.get('obligationIds',[]), *eligible]))
                    continue
                previous=reusable.get(reuse_key(frozen)) if reuse_literals else None
                if previous is not None:
                    old=by_id[previous['evidenceId']]
                    if same_metadata(old,source,quote,start,offset):
                        old['obligationIds']=list(dict.fromkeys([*old.get('obligationIds',[]),*eligible]))
                        journal['entries'][key]={'input':frozen,'evidenceId':previous['evidenceId'],
                                                'evidenceDigest':previous['evidenceDigest']}
                        continue
                ev = make_evidence(source=identity, quote=quote, original=text, location=loc,
                    obligation_ids=eligible, conditions={})
                created_quotes += 1
                ev.update(sourceId=source['sourceId'],sourceKind=source.get('sourceKind','local'),
                    sourceTitle=source.get('title',''),sourceUrl=source.get('url',''),
                    sourceQuoteStart=start,sourceContextStart=offset,extractionKind='source_passage')
                for a,b in (('ownerMaterialId','ownerMaterialId'),('sourcePublicationIdentity','publicationIdentity')):
                    if source.get(b): ev[a] = deepcopy(source[b])
                attach_table_packet(ev, source)
                if rejected_states and not literal_state_valid(ev):
                    raise DeepResearchError('invalid_source_passage_state','原文验证状态与字符检查不一致，未保存本批证据。')
                eid = ev['evidenceId']; owned_digest = digest(frozen_projection(ev))
                entry = {'input':frozen,'evidenceId':eid,'evidenceDigest':owned_digest}
                if key in journal['entries'] and journal['entries'][key] != entry:
                    raise DeepResearchError('invalid_source_passage_state','原文证据输入已改变，不能复用旧记录。')
                if eid in by_id:
                    if digest(frozen_projection(by_id[eid])) != owned_digest:
                        raise DeepResearchError('invalid_source_passage_state','已有原文证据与读取内容不一致。')
                    by_id[eid]['obligationIds'] = list(dict.fromkeys([*by_id[eid].get('obligationIds',[]), *eligible]))
                else:
                    evidence.append(ev); by_id[eid] = ev
                journal['entries'][key] = entry
                if reuse_literals:register(reusable,entry)
    # Cached pages may serve many quotes in this pure local batch. Revalidate
    # every owner before publishing its single checkpoint; no permission cache
    # crosses this boundary or permits a later provider send.
    if recheck_scope or reuse_literals:
        owners = list(dict.fromkeys(source['workId'] for source in sources))
        valid = (validate.validate_materials(run_id, owners) if batch_scope
                 else all(validate(run_id, owner) for owner in owners))
        if not valid:
            raise DeepResearchError('scope_revoked', '材料范围已变更，未保存本批原文证据。')
    # One atomic local checkpoint: never keep half a failed scope/identity batch.
    observations={}
    from services.deep_research.page_diagnostics import enabled as diagnostics_enabled,append as append_diagnostics
    diagnostic=getattr(make_evidence,'__dict__',{}).get('physical_page_diagnostics')
    if diagnostics_enabled(record) and created_quotes:
        batch=diagnostic() if callable(diagnostic) else None
        batch={**(batch or {'version':1,'quotes':created_quotes}),
               'physicalBatchAvailable':recheck_scope,'extractionSeconds':monotonic()-extraction_started}
        observations['physicalPageDiagnostics']=append_diagnostics(state.get('physicalPageDiagnostics'),batch)
    update(run_id, lambda r:{**r,'state':{**r.get('state',{}),'evidence':evidence,
        'sourcePassageExtraction':journal,**observations}}, expected_revision=None)
    return {'evidence_ids':[e['evidenceId'] for e in evidence],'extraction_pending':False}
