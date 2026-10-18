"""Prioritize explanatory passages before a bounded extraction batch."""
import re

from services.deep_research.obligation_binding import eligible_obligation_ids
from services.deep_research.selection import balanced_sample

_STOP = {'the', 'and', 'for', 'with', 'from', 'this', 'that', 'what', 'which', 'how',
         'why', 'does', 'are', 'its', 'paper', 'arxiv', 'http', 'https', 'org'}
_CAUSAL = [r'\b(?:gradient|loss|error|objective|reward|input|signal|stimulus)\w*',
           r'\b(?:updat|increas|decreas|optimi|adjust|learn|chang|modif|reduc|regulat)\w*',
           r'\b(?:if|when|while|during|after|before|unless|case|given|condition)\w*',
           r'\b(?:result|effect|influenc|efficien|qualit|accurac|outcome|output|predict|sampl|probabil|concentrat)\w*']
_METHOD_SECTION = re.compile(r'^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?'
    r'(?:(?:method(?:s|ology)?|approach|algorithm|proposed model)\b|方法|算法|模型)', re.I)
_OUTPUT_ASK = re.compile(r'\b(?:output|predict|return)\w*\b|输出|预测|返回', re.I)
_OUTPUT_DEFINITION = re.compile(r'\b(?:outputs?|predicts?|returns?)\b'
    r'|\bmaps?\s+[^.;\n]{0,100}?\s+to\b|输出|预测|映射为|返回', re.I)
_TEMPORAL_ASK = re.compile(r'\b(?:previous|preceding|prior|last|earlier)\b[^.!?\n]{0,28}?'
    r'\b(?:frames?|states?|steps?|timesteps?|representations?)\b|前一帧|上一帧|前帧|先前(?:的)?状态', re.I)
_TEMPORAL_REFERENCE = re.compile(r'\b(?:previous|preceding|prior|subsequent|next|earlier)\b'
    r'|前一帧|上一帧|下一帧|前帧|后续|先前', re.I)
_TRANSFER = re.compile(r'\b(?:initializ\w*|transform\w*|carr\w*|pass\w*|reus\w*|'
    r'propagat\w*|render\w*|condition\w*)\b|初始化|变换|传递|沿用|复用|渲染', re.I)


def _requested_operation_score(text, *, output=False, temporal=False):
    """Rank literal requested operations, never establish a factual relationship.

    A benchmark can repeat the component name without defining its output or
    state transfer. Only score co-occurring temporal references/operations in
    bounded sentences; no source text, permission or completion verdict changes.
    """
    if output:
        return int(bool(_OUTPUT_DEFINITION.search(text)))
    if temporal:
        references, operations = set(), set()
        for sentence in re.split(r'[.!?。！？\n]', text):
            if len(sentence) > 360:
                continue
            refs = {m.group().casefold() for m in _TEMPORAL_REFERENCE.finditer(sentence)}
            ops = {m.group().casefold() for m in _TRANSFER.finditer(sentence)}
            if refs and ops:
                references.update(refs);operations.update(ops)
        return min(2,len(references))+min(3,len(operations)) if references and operations else 0
    return 0


def prioritize_extraction_passages(pending, obligations, version=1):
    """Keep every unchanged passage and its permissions; this is not relevance proof.

    Explanations benefit from a complete signal/change/condition/effect chain.
    Identification-only requests keep their order. Paper round-robin prevents
    one rich source from displacing the other selected papers' first passages.
    """
    if version in (2, 3, 4):
        return _balance_obligations(pending, obligations, precise=version in (3,4), requested_operations=version==4)
    def requirement(source):
        rows = [obligations[key] for key in eligible_obligation_ids(source, obligations)]
        explain = any(any(c.get('responseType') == 'explanation' for c in row.get('completionCriteria', []))
                      or not row.get('completionCriteria') and re.search(
                          r'\b(?:how|why)\b|如何|为什么|机制|原理|怎样', row.get('question', ''), re.I)
                      for row in rows)
        query = ' '.join(str(row.get(key, '')) for row in rows for key in ('question', 'searchQuery'))
        terms = set(re.findall(r'[a-z]{3,}', query.lower())) - _STOP
        label, separator, _ = str(source.get('title', '')).partition(':')
        if separator and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', label.strip()):
            terms -= set(re.findall(r'[a-z]{3,}', label.lower()))
        return bool(explain), terms

    requirements = [requirement(source) for source, _, _ in pending]
    if not any(explain for explain, _ in requirements):
        return list(pending)
    ranked = []
    for index, (item, (explain, terms)) in enumerate(zip(pending, requirements)):
        # Normalize line-wrap hyphens only for ranking; supplied text is untouched.
        text = re.sub(r'(?<=[A-Za-z])-[ \t]*\r?\n[ \t]*(?=[A-Za-z])', '', item[2]).lower()
        causal = sum(bool(re.search(pattern, text)) for pattern in _CAUSAL) if explain else 0
        # Complete method operations outrank causal vocabulary in summaries,
        # datasets or benchmark prose. Section labels alone are not enough.
        method = bool(explain and causal >= 2 and _METHOD_SECTION.search(str(item[1].get('section', ''))))
        counts = [text.count(term) for term in terms]
        score = (method, causal, sum(count > 0 for count in counts), sum(min(count, 3) for count in counts), -index)
        ranked.append((score, item))
    ordered = [item for _, item in sorted(ranked, key=lambda row: row[0], reverse=True)]
    return balanced_sample(ordered, lambda item: item[0]['workId'], len(ordered))


def _balance_obligations(pending, obligations, precise=False, requested_operations=False):
    """A training question must not consume the motivation question's first batch."""
    papers = list(dict.fromkeys(item[0]['workId'] for item in pending))
    queues = []
    for oid, obligation in obligations.items():
        question = obligation.get('question', '')
        output_target = requested_operations and bool(_OUTPUT_ASK.search(question)) and any(
            c.get('responseType')=='identification' for c in obligation.get('completionCriteria',[]))
        temporal_target = requested_operations and bool(_TEMPORAL_ASK.search(question))
        explain = any(c.get('responseType') == 'explanation' for c in obligation.get('completionCriteria', []))
        why = bool(re.search(r'\bwhy\b|\breason|\bmotivat|为什么|为何|动机|理由|原因', question, re.I))
        terms = set(re.findall(r'[a-z]{3,}', (question + ' ' + obligation.get('searchQuery', '')).lower())) - _STOP
        if precise:
            from services.deep_research.requested_measurements import measurements
            requested = measurements(question + ' ' + obligation.get('searchQuery','') + ' ' + obligation.get('requestExcerpt',''))
        for paper in papers:
            eligible = [i for i, item in enumerate(pending)
                        if item[0]['workId'] == paper and oid in eligible_obligation_ids(item[0], obligations)]
            def score(index):
                item = pending[index]
                raw = item[2]
                if precise:
                    from services.deep_research.requested_measurements import _body
                    raw = _body({'text':raw})
                text = re.sub(r'(?<=[A-Za-z])-[ \t]*\r?\n[ \t]*(?=[A-Za-z])', '', raw).lower()
                text = re.sub(r'\s+', ' ', text)
                causal = sum(bool(re.search(pattern, text)) for pattern in _CAUSAL) if explain else 0
                motive = sum(bool(re.search(pattern, text)) for pattern in (
                    r'\b(?:because|motivat|reason|challenge|problem|limitation)\w*',
                    r'\b(?:local minim|instead of|to overcome|to address|in order to)',
                    r'原因|动机|为了解决|局部极小|局部最小')) if why else 0
                if precise and why:
                    motive += sum(bool(re.search(pattern,text)) for pattern in (
                        r'\b(?:since|therefore|thus|hence)\b',
                        r'\b(?:insufficient|unable|cannot|fails?|falters?)\b|\bfalls?\s+short\b|\bnot\s+present\b',
                        r'\b(?:essential|necessary|necessity|requires?)\b|不足|不能|缺少|因此|所以|必要'))
                method = bool(causal >= 2 and _METHOD_SECTION.search(str(item[1].get('section', ''))))
                base = (motive, method, causal, sum(term in text for term in terms), -index)
                if requested_operations:
                    base = (_requested_operation_score(text,output=output_target,temporal=temporal_target),*base)
                return (len(measurements(raw) & requested),*base) if precise else base
            if eligible:
                queues.append(sorted(eligible, key=score, reverse=True))
    selected, seen = [], set()
    while queues:
        remaining = []
        for queue in queues:
            while queue and queue[0] in seen:
                queue.pop(0)
            if queue:
                index = queue.pop(0)
                selected.append(pending[index])
                seen.add(index)
                remaining.append(queue)
        queues = remaining
    # No scoring can grant permission; callers still filter and authorize all sends.
    return [*selected, *[item for i, item in enumerate(pending) if i not in seen]]
