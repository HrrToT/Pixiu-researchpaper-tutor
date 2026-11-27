"""Route an explicitly requested like-for-like comparison recheck."""
from copy import deepcopy
import re

_ALIGN = re.compile(r'同(?:一|样|等)?(?:的)?条件|相同条件|评测条件(?:保持)?一致|同一评测设置|'
                    r'\b(?:like-for-like|same (?:evaluation )?(?:conditions|settings|protocol))\b', re.I)
_RECHECK = re.compile(r'复核|复测|重新评测|重跑|同条件对照|\b(?:recheck|re-test|re-evaluate|rerun)\b', re.I)
_PROPOSAL = re.compile(r'建议|如何|怎样|怎么|\b(?:recommend\w*|suggest\w*|how|should)\b', re.I)
_DESIGN = re.compile(r'随机分配|随机对照|训练新|重新训练|重新划分|新(?:的)?消融|干预|'
                      r'设计[^。！？；;]{0,24}实验|\b(?:train from scratch|retrain|randomi[sz]e|ablation|intervention|'
                      r'design\s+(?:an?\s+)?experiment)\b', re.I)
_DECLINES = re.compile(r'不(?:要|用|需|必)|无需|\b(?:do not|no need to|without)\b', re.I)
_PREDICTS = re.compile(r'必然|一定会|保证|将会(?:超过|优于|领先)|\b(?:guarantee\w*|will outperform|will win)\b', re.I)
_COMPARISON_BOUNDARY = re.compile(r'排序|排名|可比范围|结论范围|能支持什么|'
                                  r'\b(?:rank\w*|comparison limits|comparability limits)\b', re.I)

DRAFT_GUIDANCE = (
    'For a requested like-for-like recheck, propose only how to rerun the existing methods under '
    'the same data, input and evaluation protocol and compare the same metric. Name the concrete '
    'alignment choices that matter in this benchmark, such as sample pairs, input size or sample '
    'budget, matching or validation rules, and the measured metric. Use kind proposal '
    'with separate evidenceRefs for the existing setups from both papers. Do not claim a recheck '
    'has been performed, predict a winner, introduce new training or alter the methods.'
)

REVIEW_RULES = (
    'For these designated benchmark recheck targets ONLY, allow narrowly scoped future '
    'like-for-like measurement advice. Use adviceAudit.purpose="benchmark_recheck". Judge whether '
    'both existing methods would use aligned inputs, evaluation settings and the same metric. '
    'The proposal must be feasible and disclose unresolved alignment. Use own source-field premises '
    'from both paper versions for every embedded paper assertion. No new training, ablations, '
    'interventions, claimed execution, invented results or predicted winners.'
)


def requests_recheck(question):
    layers = getattr(question, 'point_instruction_layers', getattr(question, 'instruction_layers', (question,)))
    for layer in layers:
        for clause in re.split(r'[。！？!?；;，,\n]', layer):
            if _ALIGN.search(clause) and _RECHECK.search(clause):
                return bool(_PROPOSAL.search(clause) and not (_DESIGN.search(layer) or _DECLINES.search(clause)))
    return False


def separate_recheck_requirement(plan, question):
    """Give an explicit, already distinct recheck criterion its own answer goal."""
    from services.deep_research.evidence_requirements import _request_parts

    if not requests_recheck(question):
        return plan, []
    layers = getattr(question, 'point_instruction_layers', getattr(question, 'instruction_layers', (question,)))
    anchors = {part for layer in layers for part in _request_parts(layer)
               if len(part) >= 8 and requests_recheck(part) and not _COMPARISON_BOUNDARY.search(part)}
    if len(anchors) != 1:
        return plan, []
    recheck_excerpt, = anchors
    obligations = [o for item in plan for o in item['obligations']]
    candidates = []
    for obligation in obligations:
        role = obligation.get('comparisonRole', {})
        if (role.get('kind') != 'joint' or obligation.get('purpose') != 'answer_requirement'
                or len(set(obligation.get('requiredSources', []))) < 2):
            continue
        criteria = obligation.get('completionCriteria', [])
        rechecks = [c for c in criteria if requests_recheck(c['requirement'])]
        if rechecks and len(rechecks) == len(criteria):
            return plan, []
        if len(rechecks) != 1:
            continue
        advice, = rechecks
        if advice['responseType'] != 'procedure' or _COMPARISON_BOUNDARY.search(advice['requirement']):
            continue
        excerpt = obligation.get('requestExcerpt', '')
        boundary_parts = [part for part in _request_parts(excerpt) if len(part) >= 8
                          and not requests_recheck(part) and _COMPARISON_BOUNDARY.search(part)]
        if len(boundary_parts) == 1 and any(excerpt in layer for layer in layers):
            candidates.append((obligation, advice, boundary_parts[0]))
    if len(candidates) != 1:
        return plan, []

    original, advice, boundary_excerpt = candidates[0]
    identities = {o['obligationId'] for o in obligations}
    identity = 'benchmark_recheck'
    while identity in identities:
        identity += '_'
    remaining = [c for c in original['completionCriteria'] if c != advice]
    boundary = {**original, 'question': '\n'.join(c['requirement'] for c in remaining),
                'requestExcerpt': boundary_excerpt, 'completionCriteria': remaining,
                'comparisonRole': {'kind': 'joint', 'label': '可比性', 'requestExcerpt': boundary_excerpt}}
    recheck = {**original, 'obligationId': identity, 'question': recheck_excerpt, 'requestExcerpt': recheck_excerpt,
               'completionCriteria': [advice],
               'comparisonRole': {'kind': 'joint', 'label': '同条件复核建议', 'requestExcerpt': recheck_excerpt}}
    result = [{**item, 'obligations': [part for o in item['obligations']
              for part in ((boundary, recheck) if o is original else (o,))]} for item in plan]
    return deepcopy(result), [{'obligationId': identity, 'fromObligationId': original['obligationId'],
                               'criterionId': advice['criterionId'], 'change': 'separated_benchmark_recheck'}]


def bounded_text(text):
    aligned = _ALIGN.search(text) or re.search(r'统一|一致|相同|同一|\b(?:align\w*|match\w*|same)\b', text, re.I)
    return bool(aligned and _RECHECK.search(text) and not (_DESIGN.search(text) or _PREDICTS.search(text)))


def target_ids(record, question, claims):
    if (record.get('comparisonBenchmarkRecheckReviewVersion') not in (1, 2)
            or record.get('state', {}).get('outputKind') != 'paper_comparison'
            or not requests_recheck(question)):
        return ()
    from services.deep_research.general_advice import eligible

    goals = set()
    layers = getattr(question, 'point_instruction_layers', getattr(question, 'instruction_layers', (question,)))
    for item in record['state'].get('plan', []):
        for obligation in item.get('obligations', []):
            role = obligation.get('comparisonRole', {})
            excerpt = obligation.get('requestExcerpt', '')
            if (role.get('kind') == 'joint' and obligation.get('purpose') == 'answer_requirement'
                    and isinstance(excerpt, str) and any(excerpt in layer for layer in layers)
                    and requests_recheck(excerpt)):
                goals.add(obligation['obligationId'])
    return tuple(claim['claimId'] for claim in claims if eligible(claim)
                 and goals.intersection(claim.get('obligationIds', [])) and bounded_text(claim.get('text', '')))


def covers_two_sources(premises, own):
    works = set()
    for binding in premises:
        evidence = own[binding['evidenceId']]
        work = evidence.get('workId') or evidence.get('sourceWorkId')
        version = evidence.get('versionId') or evidence.get('sourceVersionId')
        if evidence.get('accessLevel') == 'fulltext' and work and version:
            works.add(work)
    return len(works) >= 2
