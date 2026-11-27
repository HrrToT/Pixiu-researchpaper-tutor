"""Allow source-reported joint contrasts without relabeling them as inference."""
from copy import deepcopy
import re


_SINGLE_NUMERIC_EXAMPLE = re.compile(
    r'(?:数字|数值|定量)[^\n。！？；;]{0,35}(?<!不)(?<!不要)(?<!不能)(?:只|仅)[^\n。！？；;]{0,8}(?:一|1)组[^\n。！？；;]{0,35}(?:例|对照)'
    r'|(?<!不)(?<!不要)(?<!不能)(?:只|仅)[^\n。！？；;]{0,8}(?:一|1)组[^\n。！？；;]{0,22}(?:数字|数值|定量)[^\n。！？；;]{0,18}(?:例|对照)'
    r'|(?<!not )\b(?:only|just|at most)\s+(?:one|a single|1)\s+(?:numeric(?:al)?|quantitative)\s+(?:example|comparison)\b',
    re.IGNORECASE,
)


_NUMERIC = re.compile(r'数字|数值|定量|\bnumeric(?:al)?\b|\bquantitative\b', re.I)
_BASELINE_EXAMPLE = re.compile(r'\bbaseline\s+(?:comparison\s+)?example\b|基线(?:比较|对照)?(?:示例|例子)', re.I)
_EXAMPLE_CRITERION = re.compile(r'\b(?:one|single|a single)\s+baseline comparison\b|'
                                r'\b(?:chosen|selected|paired)\s+(?:numbers|measurements|values)\b|'
                                r'\b(?:one|single)\s+bounded example\b|所选(?:数字|结果)', re.I)
_COMPARABILITY = re.compile(r'可比|能否比较|能比较|不能比较|比较(?:边界|条件)|\bcomparab\w*\b|'
                            r'\bwhat\s+(?:can|cannot)\b[^.!?]{0,60}\bbe compared\b', re.I)
_ADVICE = re.compile(r'建议|推荐|(?:有条件|如何|怎样)选择|\b(?:recommend\w*|advice|conditional choice)\b', re.I)
_SPEED = re.compile(
    r'(?<![A-Za-z0-9])(?:fps|frame\s+rate|rendering\s+(?:speed|time|latency|performance))(?![A-Za-z0-9])'
    r'|帧率|渲染(?:速度|耗时|延迟)', re.I)
_REPORTED_CONTRAST = re.compile(r'\b(?:outperform\w*|faster than|slower than|compar\w+ (?:with|to|against))\b'
                                r'|快于|慢于|优于|相比|相较', re.I)
_STORAGE = re.compile(r'存储|文件(?:体积|大小)|\b(?:storage|file size)\b', re.I)
_QUALITY = re.compile(r'画质|视觉质量|\b(?:image|visual|rendering) quality\b|\b(?:PSNR|SSIM|LPIPS)\b', re.I)
_INVENTORY = re.compile(r'两篇各自|分别列出|逐篇列出|\b(?:list|enumerate)\b[^.!?]{0,90}\b(?:each|both)\b', re.I)
_SPEED_INVENTORY = re.compile(r'各自报告|列出|\b(?:list|enumerate|report the)\b', re.I)
_PROTOCOL = re.compile(
    r'\b(?:evaluat\w*|benchmark\w*|measur\w*|render\w*|timing)\b[^.!?。]{0,120}'
    r'\b(?:on|using|with|at)\b[^.!?。]{0,80}\b(?:GPU|hardware|platform|resolution)\b'
    r'|(?:评估|测量|测试|渲染)[^。！？]{0,65}(?:显卡|GPU|硬件|分辨率)', re.I)
_REPORTED_PLATFORM = re.compile(
    r'\b(?:results?|evaluations?|experiments?|benchmarks?)\s+(?:are|were)\s+'
    r'(?:reported|conducted|run|measured|evaluated)\b[^.!?。]{0,120}'
    r'\b(?:on|using|with)\b[^.!?。]{0,80}\b(?:GPU|hardware|platform)\b', re.I)
_REQUESTED_PROTOCOL = re.compile(r'硬件|口径|适用条件|测量条件|\b(?:hardware|protocols?|conditions?|settings?)\b', re.I)


def evaluation_protocols_enabled(record):
    return (type(record.get('comparisonEvaluationProtocolVersion')) is int
            and record['comparisonEvaluationProtocolVersion'] in (1, 2, 3, 4, 5))


def deployment_memory_context_enabled(record):
    return (type(record.get('comparisonEvaluationProtocolVersion')) is int
            and record['comparisonEvaluationProtocolVersion'] in (2, 3, 4, 5))


def _evaluation_protocol_score(text):
    from services.deep_research.source_continuity import _body
    prose = ' '.join(_body({'text': text}).split())
    if _REPORTED_PLATFORM.search(prose):
        return 2
    return int(bool(_PROTOCOL.search(prose)))


def retain_evaluation_protocol(rows, candidates, record, query, pdf_id, content_hash, limit):
    """Keep a reported evaluation setting in the scoped speed query's hits."""
    if (record.get('comparisonEvaluationProtocolVersion') not in (3, 4, 5) or not content_hash
            or limit < 2 or len(rows) > limit or not _SPEED.search(query) or not _REQUESTED_PROTOCOL.search(query)):
        return rows

    def score(row):
        if (row.get('pdfId') != pdf_id or row.get('contentHash') != content_hash
                or row.get('accessLevel') != 'fulltext' or row.get('tableData')):
            return 0
        return _evaluation_protocol_score(row.get('text', ''))

    best = max(candidates, key=score, default=None)
    current = max(map(score, rows), default=0)
    if best is None or score(best) <= current:
        return rows
    if len(rows) < limit:
        return [*rows, best]
    replace = next((i for i in range(len(rows) - 1, -1, -1)
                    if not rows[i].get('tableData')
                    and rows[i].get('retrievalMode') == 'pdf_lexical_fallback'), None)
    return [*rows[:replace], best, *rows[replace + 1:]] if replace is not None else rows


def preferred_evaluation_reads(rows, obligations, limit, extracted):
    from services.deep_research.obligation_binding import eligible_obligation_ids
    from services.deep_research.reading_roles import quality

    active = {}
    for oid, obligation in obligations.items():
        question = ' '.join([obligation.get('question', ''), obligation.get('searchQuery', ''),
                             *(criterion['requirement'] for criterion in obligation.get('completionCriteria', []))])
        if _SPEED.search(question) and _REQUESTED_PROTOCOL.search(question):
            active[oid] = obligation
    if not active:
        return []
    found = {}
    for row in rows:
        if (row.get('accessLevel') != 'fulltext' or not row.get('versionId') or row.get('tableData')
                or (row['sourceId'], row.get('contentHash')) in extracted
                or not eligible_obligation_ids(row, active) or quality(row) != (True, True)):
            continue
        key = (row['workId'], row.get('versionId'))
        score = _evaluation_protocol_score(row['text'])
        if score > found.get(key, (0, None))[0]:
            found[key] = (score, row)
    return [row for _, row in list(found.values())[:limit // 3]]


def preferred_deployment_memory_reads(rows, obligations, limit, extracted, *, completion_criteria=False):
    from services.deep_research.general_advice import deployment_memory_context, requests_device_memory
    from services.deep_research.obligation_binding import eligible_obligation_ids
    from services.deep_research.reading_roles import quality

    active = {oid: row for oid, row in obligations.items() if requests_device_memory(row.get('question', ''))
              or completion_criteria and any(requests_device_memory(criterion['requirement'])
                                            for criterion in row.get('completionCriteria', []))}
    found = {}
    for row in rows:
        if (row.get('accessLevel') == 'fulltext' and row.get('versionId') and not row.get('tableData')
                and (row['sourceId'], row.get('contentHash')) not in extracted
                and eligible_obligation_ids(row, active) and quality(row) == (True, True)
                and deployment_memory_context(row['text'])):
            found.setdefault((row['workId'], row['versionId']), row)
    return list(found.values())[:limit // 6]


def has_single_numeric_example(roles):
    """Route an explicitly quoted one-example limit to its joint target."""
    return any(role['kind'] == 'joint' and _SINGLE_NUMERIC_EXAMPLE.search(role['requestExcerpt'])
               for role in roles.values())


def joint_numeric_example(roles, question):
    """Recover a joint example when another part of its goal supplies the literal anchor."""
    current_layers = getattr(question, 'point_instruction_layers', None)
    anchored_roles = roles if current_layers is None else {
        key: role for key, role in roles.items() if any(role['requestExcerpt'] in layer for layer in current_layers)
    }
    if has_single_numeric_example(anchored_roles):
        return True
    layers = current_layers if current_layers is not None else getattr(question, 'instruction_layers', (str(question),))
    return (any(_SINGLE_NUMERIC_EXAMPLE.search(layer) for layer in layers)
            and any(role['kind'] == 'joint' and _NUMERIC.search(role['question'])
                    for role in roles.values()))


def normalize_single_example_requirements(plan, question, *, include_speed_boundary=False):
    """Keep the qualitative goals when only one quantitative benchmark was requested."""
    layers = getattr(question, 'point_instruction_layers',
                     getattr(question, 'instruction_layers', (str(question),)))
    if not any(_SINGLE_NUMERIC_EXAMPLE.search(layer) for layer in layers):
        return plan, []
    result, changes = deepcopy(plan), []
    for step in result:
        for goal in step['obligations']:
            role = goal.get('comparisonRole', {})
            excerpt = role.get('requestExcerpt', '')
            if (role.get('kind') not in {'joint', 'per_paper'} or not excerpt
                    or not any(excerpt in layer for layer in layers) or _SINGLE_NUMERIC_EXAMPLE.search(excerpt)
                    or _INVENTORY.search(excerpt)):
                continue
            dimensions = [name for name, pattern in (('存储', _STORAGE), ('画质', _QUALITY), ('渲染速度', _SPEED))
                          if pattern.search(excerpt)]
            # Do not reinterpret a standalone metric request, processing costs,
            # comparability alone, or an independently explicit inventory.
            speed_boundary = (include_speed_boundary and dimensions == ['渲染速度']
                              and role['kind'] == 'joint' and _SPEED.search(goal.get('requestExcerpt', ''))
                              and re.search(r'排名|排行|排序|\brank\w*\b', goal['requestExcerpt'], re.I))
            if len(dimensions) < 2 and not speed_boundary:
                continue
            display = '、'.join(dimensions)
            subject = '比较两篇' if role['kind'] == 'joint' else '说明该论文报告'
            qualifier = f'按原文{subject}的{display}取舍及适用条件。此项用定性描述，测量值集中在一组同表同口径示例中。'
            candidates = [(goal, 'question'), *((entry, 'requirement') for entry in goal.get('completionCriteria', []))]
            for entry, field in candidates:
                text = entry[field]
                if any(text in layer for layer in layers):
                    continue
                if speed_boundary:
                    if not (_SPEED.search(text) and _SPEED_INVENTORY.search(text)):
                        continue
                    entry[field] = ('依据两篇原文说明各自如何测量渲染速度，并解释现有证据为何不能用于直接排名。'
                                    '测量结果集中在唯一的同表对照中。')
                elif (_INVENTORY.search(text)
                      and sum(bool(pattern.search(text)) for pattern in (_STORAGE, _QUALITY, _SPEED)) >= 2):
                    entry[field] = qualifier
                else:
                    continue
                changes.append({'obligationId': goal['obligationId'], 'field': field,
                                'change': 'preserved_single_benchmark_example'})
    return (result, changes) if changes else (plan, changes)


def preserve_requested_numeric_example(plan, question):
    """Keep an explicit example the model omitted from its joint obligations."""
    layers = getattr(question, 'point_instruction_layers',
                     getattr(question, 'instruction_layers', (str(question),)))
    exact = next((m.group() for layer in layers for m in _SINGLE_NUMERIC_EXAMPLE.finditer(layer)), None)
    if not exact or exact not in question:
        return plan
    obligations = [o for item in plan for o in item['obligations']]
    joint = [o for o in obligations if o.get('comparisonRole', {}).get('kind') == 'joint']
    if (not joint or any(_NUMERIC.search(' '.join([o['question'], o['comparisonRole']['requestExcerpt'],
                    *[c['requirement'] for c in o.get('completionCriteria', [])]])) for o in joint)):
        return plan
    # Keep the acquired/search source scope inside the existing joint plan.
    sources = list(dict.fromkeys(s for o in joint for s in o.get('requiredSources', [])))
    oid = 'requested_numeric_example'
    identities = {o['obligationId'] for o in obligations}
    while oid in identities:
        oid += '_'
    result = deepcopy(plan)
    step = next(item for item in result if any(o.get('comparisonRole', {}).get('kind') == 'joint'
                                               for o in item['obligations']))
    requirement = '给出一组来源明确、数据组和测量口径对齐的原文基线对照数字，并说明适用条件。'
    step['obligations'].append({'obligationId': oid, 'question': requirement, 'requestExcerpt': exact,
        'searchQuery':'baseline benchmark results evaluation protocol dataset hardware',
        'purpose':'answer_requirement','requiredSources':sources,
        'comparisonRole': {'kind':'joint','label':'同口径数字示例','requestExcerpt':exact},
        'completionCriteria':[{'criterionId':'matched_example','requirement':requirement,
                               'responseType':'identification'}]})
    return result


def preserve_requested_memory_advice(plan, question):
    """Recover a literal advice clause omitted from a merged comparison goal."""
    from services.deep_research.comparison_cross_paper_boundary import explicitly_requests_cross_paper_speed
    from services.deep_research.evidence_requirements import _request_parts
    from services.deep_research.general_advice import requests_device_memory

    if not explicitly_requests_cross_paper_speed(question):
        return plan, []

    def is_memory_advice(text):
        return bool(requests_device_memory(text) and _ADVICE.search(text))

    obligations = [obligation for step in plan for obligation in step['obligations']]
    if any(is_memory_advice(criterion['requirement']) for obligation in obligations
           for criterion in obligation.get('completionCriteria', [])):
        return plan, []
    layers = getattr(question, 'instruction_layers', (str(question),))
    result = deepcopy(plan)
    for step in result:
        for obligation in step['obligations']:
            role = obligation.get('comparisonRole', {})
            excerpt = obligation.get('requestExcerpt', '')
            criteria = obligation.get('completionCriteria', [])
            if (role.get('kind') != 'joint' or len(criteria) != 1 or not excerpt
                    or not any(excerpt in layer for layer in layers)
                    or not explicitly_requests_cross_paper_speed(criteria[0]['requirement'])):
                continue
            clauses = [part for part in _request_parts(excerpt)
                       if is_memory_advice(part) and not _SPEED.search(part)]
            if len(clauses) != 1 or criteria[0]['criterionId'] == 'literal_memory_advice':
                continue
            criteria.append({'criterionId': 'literal_memory_advice', 'requirement': clauses[0],
                             'responseType': 'explanation'})
            return result, [{'obligationId': obligation['obligationId'], 'change': 'preserved_memory_advice'}]
    return plan, []


def place_cross_paper_speed_criterion(plan, question):
    """Move a misplaced comparison criterion to a joint obligation before retrieval."""
    from services.deep_research.comparison_cross_paper_boundary import explicitly_requests_cross_paper_speed
    from services.deep_research.evidence_requirements import _request_parts

    layers = getattr(question, 'point_instruction_layers', (str(question),))
    anchors = set(part for layer in layers for part in _request_parts(layer)
                  if explicitly_requests_cross_paper_speed(part))
    if len(anchors) != 1:
        return plan, []
    anchor, = anchors

    def is_boundary(text):
        return explicitly_requests_cross_paper_speed(text) and bool(
            _COMPARABILITY.search(text)
            or re.search(r'排名|排行|排序|相除|比值|不能直接比较|\b(?:rank\w*|ratio|divide)\b', text, re.I))

    result = deepcopy(plan)
    obligations = [o for step in result for o in step['obligations']]
    if any(o['comparisonRole']['kind'] == 'joint' and any(is_boundary(part)
            for part in (o['comparisonRole']['requestExcerpt'], o['question'],
                         *(c['requirement'] for c in o.get('completionCriteria', [])))) for o in obligations):
        return plan, []
    matches = [(step, o, c) for step in result for o in step['obligations']
               if o['comparisonRole']['kind'] == 'per_paper' and len(o.get('completionCriteria', [])) > 1
               and len(set(o.get('requiredSources', []))) >= 2
               for c in o['completionCriteria']
               if is_boundary(c['requirement'])]
    if len(matches) != 1:
        return plan, []
    step, original, criterion = matches[0]
    oid = 'requested_speed_comparability'
    identities = {o['obligationId'] for o in obligations}
    while oid in identities:
        oid += '_'
    original['completionCriteria'].remove(criterion)
    step['obligations'].append({**original, 'obligationId': oid, 'question': anchor, 'requestExcerpt': anchor,
        'searchQuery': 'FPS rendering speed evaluation protocol hardware resolution scene timing',
        'comparisonRole': {'kind': 'joint', 'label': '跨论文帧率可比性', 'requestExcerpt': anchor},
        'completionCriteria': [criterion]})
    return result, [{'obligationId': oid, 'sourceObligationId': original['obligationId'],
                     'criterionId': criterion['criterionId'], 'change': 'placed_cross_paper_speed_criterion'}]


def split_joint_deliverables(roles, requirements, question, *, classify_standalone=False,
                             separate_example_boundary=False, group_example_criteria=False,
                             split_speed_and_advice=False, preserve_mixed_speed_criteria=False):
    """Assign distinct outputs without losing or duplicating any frozen criterion."""
    from services.deep_research.comparison_cross_paper_boundary import explicitly_requests_cross_paper_speed
    split_speed_and_advice = split_speed_and_advice and explicitly_requests_cross_paper_speed(question)
    numeric_example = joint_numeric_example(roles, question)
    if not (numeric_example or split_speed_and_advice):
        return {}
    result = {}
    for obligation in requirements:
        oid = obligation['obligationId']
        criteria = obligation.get('completionCriteria', [])
        if roles[oid]['kind'] != 'joint':
            continue
        if split_speed_and_advice and preserve_mixed_speed_criteria:
            advice = [c['requirement'] for c in criteria if _ADVICE.search(c['requirement'])]
            other = [c['requirement'] for c in criteria if not _ADVICE.search(c['requirement'])]
            speed_request = any(explicitly_requests_cross_paper_speed(part) for part in (
                obligation['question'], roles[oid]['requestExcerpt'], *(c['requirement'] for c in criteria)))
            if advice and speed_request:
                if (any(_SPEED.search(part) for part in other)
                        and not any(_SPEED.search(part) for part in advice)
                        and not any(_NUMERIC.search(part) or _BASELINE_EXAMPLE.search(part)
                                    or _EXAMPLE_CRITERION.search(part) for part in other)):
                    result[oid] = [{'kind': 'comparability', 'requirement': '\n'.join(other)},
                                   {'kind': 'conditional_advice', 'requirement': '\n'.join(advice)}]
                # An ambiguous combined criterion stays attached to the general
                # joint target. Classifying it as advice alone drops the boundary.
                continue
        if split_speed_and_advice and len(criteria) == 2:
            speed = [c for c in criteria if _SPEED.search(c['requirement'])
                     and (_COMPARABILITY.search(c['requirement'])
                          or re.search(r'排名|排行|排序|\brank\w*\b', c['requirement'], re.I))
                     and not _ADVICE.search(c['requirement'])]
            advice = [c for c in criteria if _ADVICE.search(c['requirement'])]
            if len(speed) == len(advice) == 1:
                result[oid] = [{'kind':'comparability','requirement':speed[0]['requirement']},
                               {'kind':'conditional_advice','requirement':advice[0]['requirement']}]
                continue
        if not numeric_example:
            continue
        if separate_example_boundary and _SINGLE_NUMERIC_EXAMPLE.search(roles[oid]['requestExcerpt']):
            identified = {}
            for criterion in criteria:
                requirement = criterion['requirement']
                if _ADVICE.search(requirement):
                    kind = 'conditional_advice'
                elif _COMPARABILITY.search(requirement):
                    kind = 'comparability'
                elif (_NUMERIC.search(requirement) or _BASELINE_EXAMPLE.search(requirement)
                      or group_example_criteria and _EXAMPLE_CRITERION.search(requirement)):
                    kind = 'matched_example'
                else:
                    break
                if kind in identified:
                    if kind != 'matched_example' or not group_example_criteria:
                        break
                    requirement = identified[kind]['requirement'] + '\n' + requirement
                identified[kind] = {'kind': kind, 'requirement': requirement}
            else:
                if 'matched_example' in identified:
                    result[oid] = list(identified.values())
                    continue
        numeric = [c for c in criteria if _NUMERIC.search(c['requirement']) and not _ADVICE.search(c['requirement'])]
        advice = [c for c in criteria if _ADVICE.search(c['requirement']) and not _NUMERIC.search(c['requirement'])]
        if len(criteria) == 2 and len(numeric) == len(advice) == 1:
            result[oid] = [
                {'kind': 'matched_example', 'requirement': numeric[0]['requirement']},
                {'kind': 'conditional_advice', 'requirement': advice[0]['requirement']},
            ]
        elif classify_standalone:
            anchor = roles[oid]['requestExcerpt']
            if _SINGLE_NUMERIC_EXAMPLE.search(anchor) and numeric and not advice:
                result[oid] = [{'kind':'matched_example','requirement':obligation['question']}]
            elif _ADVICE.search(anchor) and advice and not numeric:
                result[oid] = [{'kind':'conditional_advice','requirement':obligation['question']}]
    return result


def enabled(record):
    from services.deep_research.comparison_intent import operations_enabled
    return (operations_enabled(record) and type(record.get('comparisonJointReportsContractVersion')) is int
            and record['comparisonJointReportsContractVersion'] in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16))


def resource_allocation_enabled(record):
    return enabled(record) and record['comparisonJointReportsContractVersion'] in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)


def benchmark_example_obligation(record, plan):
    """Identify a requested single example from server-owned deliverable metadata."""
    version = record.get('comparisonJointReportsContractVersion')
    if type(version) is not int or version not in (5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16):
        return None
    matches = [oid for oid, parts in plan.get('jointDeliverables', {}).items()
               for part in parts if part['kind'] == 'matched_example']
    return matches[0] if len(matches) == 1 else None


def benchmark_example_owner(record, plan):
    oid = benchmark_example_obligation(record, plan)
    return f'joint_{oid}_matched_example' if oid is not None else None


def bind_benchmark_example(record, draft, plan):
    if record.get('comparisonJointReportsContractVersion') not in (6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16):
        return
    oid = benchmark_example_obligation(record, plan)
    if oid is None:
        return
    cells = {cid for row in draft['layout'] for cid in row['claimIds']}
    matches = [claim['claimId'] for claim in draft['report']['claims']
               if claim['claimId'] not in cells and claim['kind'] == 'reported'
               and claim['obligationIds'] == [oid]]
    draft['benchmarkExampleClaimId'] = matches[0] if len(matches) == 1 else None
    if strict_benchmark_speed_scope(record):
        version = record['comparisonBenchmarkSpeedScopeContractVersion']
        draft['benchmarkSpeedScopeVersion'] = 3 if version in (6, 7) else 2 if version in (3, 4, 5) else 1
    if scoped_example_presentation(record) in (3, 4) and len(matches) == 1:
        from services.deep_research.benchmark_tradeoff_summary import INTRO_PREFIX
        example = next(claim for claim in draft['report']['claims'] if claim['claimId'] == matches[0])
        if example.get('body', {}).get('prose', {}).get('text', '').startswith(INTRO_PREFIX):
            draft['beginnerLeadClaimId'] = matches[0]


def strict_benchmark_speed_scope(record):
    version = record.get('comparisonBenchmarkSpeedScopeContractVersion')
    return type(version) is int and version in (1, 2, 3, 4, 5, 6, 7)


def scoped_example_presentation(record):
    version = record.get('comparisonBenchmarkSpeedScopeContractVersion')
    if version in (4, 5, 6, 7):
        from services.deep_research.audience_rewrite import beginner_requested
        return (4 if version == 7 else 3) if beginner_requested(record) else 2
    return 2 if version in (2, 3) else True


_NUMERIC_FRAME_RATE = re.compile(
    r'(?:\d\s*\+?\s*(?:fps\b|frames?\s*(?:/|per\s+)\s*(?:s\b|seconds?\b)|帧\s*(?:/|每)\s*秒)'
    r'|(?:\bfps|帧率)\s*[:：=]\s*[<>≤≥~≈+-]?\s*\d)', re.I)
_VALUE_AFTER_FRAME_RATE = re.compile(
    r'(?:(?<![A-Za-z0-9])fps(?![A-Za-z0-9])|帧率)\s*(?:分别)?\s*(?:为|是|约为|达到|达|超过|低于|约|\b(?:was|were|is|of|reached)\b)'
    r'\s*[<>≤≥~≈+-]?\s*\d', re.I)
_RELATIVE_FRAME_RATE = re.compile(
    rf'(?:{_SPEED.pattern})[^。！？；，、.!?;,\n]{{0,36}}?'
    r'(?:翻倍|减半|[零一二两三四五六七八九十百]+\s*倍|'
    r'\d+(?:\.\d+)?\s*(?:[%％×]|倍|x\b|[- ]fold\b|times\b)|'
    r'\b(?:doubl(?:e|ed|es|ing)|tripl(?:e|ed|es|ing)|half|halved|twice|three times)\b)'
    rf'|\b(?:twice|three times|\d+(?:\.\d+)?\s*(?:x\b|times\b))'
    rf'\s+(?:as\s+)?(?:fast|high|faster|higher|lower|the)\b[^.!?;,\n]{{0,16}}?(?:{_SPEED.pattern})'
    rf'|\b(?:doubl(?:e|ed|es|ing)|tripl(?:e|ed|es|ing)|halv(?:e|ed|es|ing))'
    rf'\s+(?:(?:the|reported|measured|average)\s+)*?(?:{_SPEED.pattern})',
    re.I)


def _benchmark_scope_text(claim, draft):
    text = str(claim.get('text', ''))
    authored = next((row for row in draft.get('report', {}).get('claims', [])
                     if row['claimId'] == claim['claimId']), {})
    boundary = authored.get('body', {}).get('boundary')
    if boundary is None or claim.get('kind') != 'inference':
        return text

    from services.deep_research.scope_expression import materialize
    source_titles = {source.get('title') for source in draft.get('sources', {}).values()}
    canonical = {**claim, 'text': '', 'conditions': {}, 'scopeExpression': boundary}
    try:
        rendered, _ = materialize(canonical, 5)
        if rendered['text'] != text:
            return text

        # A publisher's title can contain a frame rate. Mask only literal titles
        # in subject positions of an unchanged, application-rendered boundary.
        masked = deepcopy(boundary)
        for setting in masked['observedSettings']:
            if setting['subject'] in source_titles:
                setting['subject'] = '论文'
        for proposition in masked['notEstablished']:
            if proposition.get('type') == 'comparison_evidence':
                proposition['subjects'] = [f'论文{i}' if subject in source_titles else subject
                                           for i, subject in enumerate(proposition['subjects'], 1)]
        rendered, _ = materialize({**canonical, 'scopeExpression': masked}, 5)
        return rendered['text']
    except ValueError:
        return text


def benchmark_binding_error(claim, draft):
    """Recheck typed benchmark ownership and the one paired table group after edits."""
    from services.deep_research.measurement_table_navigation import benchmark_metric
    bindings = claim.get('tableBindings') or []
    if claim['claimId'] != draft['benchmarkExampleClaimId']:
        if any(isinstance(binding, dict) and isinstance(binding.get('metric'), str)
               and benchmark_metric(binding['metric']) for binding in bindings):
            return 'comparison_benchmark_example_scope'
        scope_version = draft.get('benchmarkSpeedScopeVersion')
        if scope_version in (1, 2, 3):
            conditions = claim.get('conditions')
            fields = [_benchmark_scope_text(claim, draft)]
            if isinstance(conditions, dict):
                fields.extend(f'{key}: {value}' for key, value in conditions.items())
            if any(_NUMERIC_FRAME_RATE.search(field) or
                   scope_version >= 2 and _VALUE_AFTER_FRAME_RATE.search(field) or
                   scope_version == 3 and _RELATIVE_FRAME_RATE.search(field) for field in fields):
                return 'comparison_benchmark_example_scope'
        return None
    if not bindings:
        return None  # A prose-only example still requires ordinary source and semantic verification.
    methods = {}
    groups = set()
    for binding in bindings:
        if (not isinstance(binding, dict) or not isinstance(binding.get('evidenceId'), str)
                or type(binding.get('groupIndex')) is not int or type(binding.get('rowNumber')) is not int
                or not isinstance(binding.get('metric'), str)):
            return 'comparison_benchmark_example_pair'
        groups.add((binding['evidenceId'], binding['groupIndex']))
        methods.setdefault(binding['rowNumber'], set()).add(binding['metric'])
    if len(groups) != 1 or len(methods) != 2 or len({frozenset(metrics) for metrics in methods.values()}) != 1:
        return 'comparison_benchmark_example_pair'
    return None


def resolved_benchmark_gap_keys(draft, audit, claims, evidence, coverage, missing):
    """A verified same-table example can replace an inconclusive joint search."""
    from services.deep_research.comparison_presentation import audit_digest, metadata
    from services.deep_research.table_bindings import validate_table_bindings

    if not draft or audit.get('status') != 'checked':
        return set()
    cid = draft.get('benchmarkExampleClaimId')
    rows = [claim for claim in claims if claim.get('claimId') == cid]
    if not cid or len(rows) != 1:
        return set()
    claim, = rows
    targets = claim.get('obligationIds', [])
    if (len(targets) != 1 or claim.get('kind') != 'reported' or claim.get('verification') != 'semantic_passed'
            or not claim.get('tableBindings') or benchmark_binding_error(claim, draft)):
        return set()
    oid, = targets
    if (oid in missing or oid in audit.get('invalidAspectObligations', [])
            or oid in audit.get('invalidCriterionObligations', [])
            or [item['kind'] for item in draft.get('jointDeliverables', {}).get(oid, [])] != ['matched_example']):
        return set()
    decisions = [row for row in audit.get('verdicts', []) if row.get('obligationId') == oid]
    if (len(decisions) != 1 or decisions[0].get('status') != 'covered'
            or {item.get('claimId') for item in decisions[0].get('bindings', [])} != {cid}
            or audit.get('comparisonPresentationDigest') != audit_digest(metadata(draft), claims)):
        return set()
    refs = claim.get('evidenceRefs', [])
    support = [row for row in evidence if row['evidenceId'] in refs
               and row.get('accessLevel') == 'fulltext' and row.get('verification', {}).get('literal') == 'passed']
    aliases = {alias for goal in draft.get('jointGoals', []) if goal['obligationId'] == oid
               for alias in goal['sourceAliases']}
    allowed = {(source.get('workId'), source.get('versionId')) for alias, source in draft['sources'].items()
               if alias in aliases and source.get('workId') and source.get('versionId')}
    if (len(support) != len(refs) or {row['evidenceId'] for row in support} != set(refs)
            or any((row.get('sourceWorkId'), row.get('sourceVersionId')) not in allowed for row in support)
            or validate_table_bindings(claim, support)):
        return set()
    # These are per-paper copies of a joint readiness result. Keep the
    # original retrieval history and every ordinary paper-specific gap.
    return {(oid, row['sourceWorkId'], row['missingEvidence']) for row in coverage
            if row.get('obligationId') == oid and row.get('supportKind') == 'joint'
            and row.get('state') == 'unchecked' and row.get('missingEvidence')}


def comparison_protocol_priority(rows, targets, *, reported_platform=False, explicit_targets=False):
    """Reserve optional priority for one evaluation-protocol passage per relevant source."""
    relevant_sources = {source for target in targets
                        if target['role'] == 'joint' and (not target.get('deliverable')
                            or explicit_targets and target['deliverable'] == 'comparability')
                        and _SPEED.search(target['question']) for source in target['sources']}
    prioritized = {}
    for row in rows:
        source = row['source']
        if (source in relevant_sources and row.get('accessLevel') == 'fulltext'
                and not (row.get('tableData') or row.get('tableDataRef'))):
            score = _evaluation_protocol_score(row['quote']) if reported_platform else int(bool(_PROTOCOL.search(row['quote'])))
            if score > prioritized.get(source, (0, None))[0]:
                prioritized[source] = (score, row['evidenceId'])
    return {eid for _, eid in prioritized.values()}


def preferred_speed_result(rows, targets, source):
    """Prefer a literal contrast before optional prose for a paper's speed row."""
    if not any(target['role'] == 'paper_cell' and target['source'] == source
               and _SPEED.search(target['question']) for target in targets):
        return ()
    from services.deep_research.quote_context import _sentence_cuts

    for row in rows:
        if (row['source'] != source or row.get('accessLevel') != 'fulltext'
                or row.get('tableData') or row.get('tableDataRef')):
            continue
        text = ' '.join(row['quote'].split())
        cuts = [0, *_sentence_cuts(text), len(text)]
        for start, end in zip(cuts, cuts[1:]):
            sentence = text[start:end].strip()
            if (sentence and sentence[0].isalpha() and _SPEED.search(sentence)
                    and _REPORTED_CONTRAST.search(sentence)):
                return (row['evidenceId'],)
    return ()


def deployment_memory_priority(rows, targets):
    from services.deep_research.general_advice import deployment_memory_context, requests_device_memory

    allowed = {eid for target in targets if target.get('deliverable') == 'conditional_advice'
               and requests_device_memory(target['question']) for eid in target['evidenceIds']}
    found = {}
    for row in rows:
        if (row['evidenceId'] in allowed and row.get('accessLevel') == 'fulltext'
                and not (row.get('tableData') or row.get('tableDataRef'))
                and deployment_memory_context(row['quote'])):
            found.setdefault(row['source'], row['evidenceId'])
    return set(found.values())


PLANNING = '''Use joint for a shared source-reported contrast or numerical example as well as
comparability, tradeoffs and conditional choice. A requested SINGLE baseline example
is one joint deliverable, not a separate numerical inventory for every paper.
One permitted publication may report both baseline and compared method. The required
material scope is not a demand for every number to appear in every paper.
Keep all independently requested per-paper mechanisms/costs and joint limitations.
Do not invent facts, simplify away dimensions or demand extra examples.'''

GENERATION = '''Joint targets may use kind=reported for a contrast directly reported by
their own permitted original sources; never relabel a reported measurement as inference
to fit the protocol. One publication can report both baseline and compared method.
Preserve baseline identity/variant, measured group, metric, unit and protocol in the
same point, with exact own tableBindings where applicable. Ordinary Ours outside a
paper-column cell needs its explicit source method identity, not a borrowed heading.
Respect the human's requested number of examples ACROSS the whole answer: do not
repeat the same numerical inventory in paper cells and the joint point. Select the
minimum sufficient matched example; retain necessary contrary results and all
mechanism/cost/comparability/choice goals. No source or format grants approval.'''
