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
_ADVICE = re.compile(r'建议|推荐|(?:有条件|如何|怎样)选择|\b(?:recommend\w*|advice|conditional choice)\b', re.I)
_SPEED = re.compile(
    r'(?<![A-Za-z0-9])(?:fps|frame\s+rate|rendering\s+(?:speed|time|latency|performance))(?![A-Za-z0-9])'
    r'|帧率|渲染(?:速度|耗时|延迟)', re.I)
_PROTOCOL = re.compile(
    r'\b(?:evaluat\w*|benchmark\w*|measur\w*|render\w*|timing)\b[^.!?。]{0,120}'
    r'\b(?:on|using|with|at)\b[^.!?。]{0,80}\b(?:GPU|hardware|platform|resolution)\b'
    r'|(?:评估|测量|测试|渲染)[^。！？]{0,65}(?:显卡|GPU|硬件|分辨率)', re.I)


def has_single_numeric_example(roles):
    """Route an explicitly quoted one-example limit to its joint target."""
    return any(role['kind'] == 'joint' and _SINGLE_NUMERIC_EXAMPLE.search(role['requestExcerpt'])
               for role in roles.values())


def joint_numeric_example(roles, question):
    """Recover a joint example when another part of its goal supplies the literal anchor."""
    if has_single_numeric_example(roles):
        return True
    layers = getattr(question, 'instruction_layers', (str(question),))
    return (any(_SINGLE_NUMERIC_EXAMPLE.search(layer) for layer in layers)
            and any(role['kind'] == 'joint' and _NUMERIC.search(role['question'])
                    for role in roles.values()))


def preserve_requested_numeric_example(plan, question):
    """Keep an explicit example the model omitted from its joint obligations."""
    layers = getattr(question, 'instruction_layers', (str(question),))
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


def split_joint_deliverables(roles, requirements, question, *, classify_standalone=False):
    """Split a mixed goal only when its frozen criteria distinguish both deliverables."""
    if not joint_numeric_example(roles, question):
        return {}
    result = {}
    for obligation in requirements:
        oid = obligation['obligationId']
        criteria = obligation.get('completionCriteria', [])
        if roles[oid]['kind'] != 'joint':
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
            and record['comparisonJointReportsContractVersion'] in (1, 2, 3, 4))


def resource_allocation_enabled(record):
    return enabled(record) and record['comparisonJointReportsContractVersion'] in (2, 3, 4)


def comparison_protocol_priority(rows, targets):
    """Reserve optional priority for one evaluation-protocol passage per relevant source."""
    relevant_sources = {source for target in targets
                        if target['role'] == 'joint' and not target.get('deliverable')
                        and _SPEED.search(target['question']) for source in target['sources']}
    prioritized = set()
    for row in rows:
        source = row['source']
        if (source in relevant_sources and row.get('accessLevel') == 'fulltext'
                and not (row.get('tableData') or row.get('tableDataRef')) and _PROTOCOL.search(row['quote'])):
            prioritized.add(row['evidenceId'])
            relevant_sources.remove(source)
    return prioritized


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
