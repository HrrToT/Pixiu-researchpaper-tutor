"""Save original read passages without model transcription or semantic approval."""
from copy import deepcopy
import re

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


def body_start(source, location, text):
    prefix = f"Paper: {source.get('title')}\n\nSection: {location.get('section')}\n\nContent:\n"
    if text.startswith(prefix): return len(prefix)
    match = WRAPPER.match(text)
    if match:
        if (match['title'] != source.get('title') or match['section'] != location.get('section')):
            raise DeepResearchError('invalid_source_passage','读取片段的正文包装与来源信息不一致，未提取证据。')
        return match.end()
    return 0


def projection(evidence):
    return {key:deepcopy(evidence[key]) for key in OWNED if key in evidence}


def extract(record, make_evidence, validate, update):
    run_id = record['runId']; state = record.get('state', {})
    canonical = record['adaptiveExtractionContractVersion'] == 3
    input_version = 2 if canonical else 1
    sources = state.get('readResults', [])
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
                or entry['evidenceDigest'] != digest(projection(by_id[entry['evidenceId']]))):
            raise DeepResearchError('invalid_source_passage_state','保存的原文证据或输入摘要已改变，不能继续提取。')
        old = by_id[entry['evidenceId']]; frozen = entry['input']
        if (old.get('verification',{}).get('literal') != 'passed'
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
    batch_scope = callable(getattr(type(validate), 'validate_materials', None))
    if batch_scope and not validate.validate_materials(run_id, list(dict.fromkeys(s['workId'] for s in sources))):
        raise DeepResearchError('scope_revoked','材料范围核对未通过，尚未提取原文证据。')
    units = 0
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
            offset = body_start(source, location, text)
            body = text[offset:]
            ranges = list(spans(body))
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
                ev = make_evidence(source=identity, quote=quote, original=text, location=loc,
                    obligation_ids=eligible, conditions={})
                ev.update(sourceId=source['sourceId'],sourceKind=source.get('sourceKind','local'),
                    sourceTitle=source.get('title',''),sourceUrl=source.get('url',''),
                    sourceQuoteStart=start,sourceContextStart=offset,extractionKind='source_passage')
                for a,b in (('ownerMaterialId','ownerMaterialId'),('sourcePublicationIdentity','publicationIdentity')):
                    if source.get(b): ev[a] = deepcopy(source[b])
                attach_table_packet(ev, source)
                eid = ev['evidenceId']; owned_digest = digest(projection(ev))
                entry = {'input':frozen,'evidenceId':eid,'evidenceDigest':owned_digest}
                if key in journal['entries'] and journal['entries'][key] != entry:
                    raise DeepResearchError('invalid_source_passage_state','原文证据输入已改变，不能复用旧记录。')
                if eid in by_id:
                    if digest(projection(by_id[eid])) != owned_digest:
                        raise DeepResearchError('invalid_source_passage_state','已有原文证据与读取内容不一致。')
                    by_id[eid]['obligationIds'] = list(dict.fromkeys([*by_id[eid].get('obligationIds',[]), *eligible]))
                else:
                    evidence.append(ev); by_id[eid] = ev
                journal['entries'][key] = entry
    # One atomic local checkpoint: never keep half a failed scope/identity batch.
    update(run_id, lambda r:{**r,'state':{**r.get('state',{}),'evidence':evidence,
        'sourcePassageExtraction':journal}}, expected_revision=None)
    return {'evidence_ids':[e['evidenceId'] for e in evidence],'extraction_pending':False}
