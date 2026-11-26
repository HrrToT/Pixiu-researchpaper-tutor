"""Keep cross-paper speed questions attached to their selected publications."""
from collections import Counter
import re

from services.deep_research.comparison_joint_reports import _SPEED
from services.deep_research.source_labels import source_display_title


CROSS_PAPER = re.compile(r'跨论文|(?:两|二|2)篇|不同论文|\bcross[- ](?:paper|study)\b|'
                         r'\b(?:both|two|different)\s+(?:papers|studies)\b|\bacross (?:the )?(?:papers|studies)\b', re.I)
_UNKNOWN_SETTING = re.compile(
    r'(?:未(?:在(?:当前|所引|引用|提供的)?证据中)?(?:明确)?(?:说明|报告|给出)'
    r'|(?:not (?:specified|reported|stated)|unspecified)'
    r'(?: in (?:the )?(?:cited|supplied|provided) (?:evidence|sources))?)'
    r'(?:\s*(?:（[^()（）\r\n]{1,240}）|\([^()（）\r\n]{1,240}\)))?',
    re.I,
)
POLICY = ('For targets with paperSubjects, compare those publication IDs, not method-row labels. '
          'Cite evidence owned by each paper. In body.boundary use the exact paper IDs as '
          'observedSettings.subject and comparison_evidence.subjects. Each setting needs its own evidenceRefs '
          'from that paper. List only source-supported settings in observedSettings. Leave unknown settings out '
          'of that list and explain the comparison the citations cannot establish in notEstablished. '
          'The app displays their publication titles. If the citations do establish alignment, '
          'answer with evidence-backed prose instead of asserting a gap. If there is no grounded answer, use null.\n')
COMPACT_POLICY = ('For paperSubjects, use those exact publication IDs in observedSettings.subject and comparison_evidence.subjects. '
                  'Cite both papers and give each known setting its own evidenceRefs from its paper. Omit unknown settings. '
                  'Use notEstablished for comparisons the two citations do not establish. If they establish alignment, explain it with citations. '
                  'Return null if no answer is grounded.\n')
TYPED_POLICY = ('For paperSubjects use exact publication IDs in comparison_evidence.subjects and each observedSettings item: '
                '{"subject":"P_ID","attribute":"name","value":"stated value","evidenceRefs":["E_ID"]}. '
                'Cite both papers and cite each known setting from its paper. Omit unknown settings. '
                'Use notEstablished for comparisons the citations do not establish. Explain established alignment with citations. '
                'Return null if no answer is grounded.\n')


def explicitly_requests_cross_paper_speed(question):
    layers = getattr(question, 'instruction_layers', (str(question),))
    return any(CROSS_PAPER.search(clause) and _SPEED.search(clause)
               for layer in layers for clause in re.split(r'[。！？!?；;\n]', layer))


def scopes(record, plan, targets, *, question=None):
    version = record.get('comparisonCrossPaperBoundaryContractVersion')
    if type(version) is not int or version not in (1, 2, 3, 4, 5, 6):
        return {}
    explicit_request = version >= 2 and explicitly_requests_cross_paper_speed(question)
    requirements = {row['obligationId']: row for row in plan.get('requirements', [])}
    result = {}
    for target in targets:
        if target['role'] != 'joint' or target.get('deliverable') in {'matched_example', 'conditional_advice'}:
            continue
        oid, = target['allowedObligationIds']
        role = plan['roles'][oid]
        request = role['requestExcerpt']
        papers = target['sources']
        local_speed = CROSS_PAPER.search(request) and _SPEED.search(request)
        split_speed = (explicit_request and target.get('deliverable') == 'comparability'
                       and _SPEED.search(target['question']))
        # Role excerpts can be shorter than the user's requirement. Use only
        # this target's frozen question and criteria to recover its meaning.
        frozen_speed = False
        if version in (3, 4, 5, 6) and explicit_request:
            criteria = requirements.get(oid, {}).get('completionCriteria', [])
            question_parts = [target['question'], *(row['requirement'] for row in criteria)]
            frozen_speed = any(explicitly_requests_cross_paper_speed(part) for part in question_parts)
        if len(papers) >= 2 and (local_speed or split_speed or frozen_speed):
            result[target['targetId']] = papers
    return result


def compile_point(point, papers, sources, evidence_owners):
    """Resolve model-selected publication aliases without inferring evidence or settings."""
    refs = point.get('evidenceRefs')
    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
        raise ValueError('stage_cross_paper_evidence')
    if {evidence_owners.get(ref) for ref in refs} != set(papers):
        raise ValueError('stage_cross_paper_evidence')
    body = point.get('body')
    if not isinstance(body, dict) or set(body) != {'boundary'}:
        return point
    boundary = body['boundary']
    if not isinstance(boundary, dict) or set(boundary) != {'observedSettings', 'notEstablished'}:
        raise ValueError('stage_cross_paper_boundary')
    settings, limits = boundary['observedSettings'], boundary['notEstablished']
    if not isinstance(settings, list) or not isinstance(limits, list) or not limits:
        raise ValueError('stage_cross_paper_boundary')
    labels = {paper: source_display_title(sources[paper].get('title'), paper) for paper in papers}
    counts = Counter(labels.values())
    for paper, title in list(labels.items()):
        if counts[title] > 1:
            publication = sources[paper].get('publicationIdentity') or {}
            labels[paper] = f'{title} ({publication.get("displayId") or paper})'
    resolved_settings = []
    for setting in settings:
        paper = setting.get('subject') if isinstance(setting, dict) else None
        anchors = setting.get('evidenceRefs') if isinstance(setting, dict) else None
        if (not isinstance(paper, str) or paper not in labels or not isinstance(anchors, list)
                or any(not isinstance(ref, str) or ref not in refs or evidence_owners.get(ref) != paper for ref in anchors)):
            raise ValueError('stage_cross_paper_setting_owner')
        value = setting.get('value')
        if (set(setting) == {'subject', 'attribute', 'value', 'evidenceRefs'}
                and isinstance(setting['attribute'], str) and setting['attribute'].strip()
                and isinstance(value, str) and _UNKNOWN_SETTING.fullmatch(value.strip().rstrip('。.!'))):
            continue  # The gap and its parenthetical explanation supply no observed value.
        if not anchors:
            raise ValueError('stage_cross_paper_setting_owner')
        resolved_settings.append({**setting, 'subject': labels[paper]})
    resolved_limits = []
    for limit in limits:
        subjects = limit.get('subjects') if isinstance(limit, dict) else None
        if (not isinstance(limit, dict) or limit.get('type') != 'comparison_evidence'
                or not isinstance(subjects, list) or len(subjects) != len(papers)
                or any(not isinstance(subject, str) for subject in subjects) or set(subjects) != set(papers)):
            raise ValueError('stage_cross_paper_subjects')
        resolved_limits.append({**limit, 'subjects': [labels[paper] for paper in subjects]})
    return {**point, 'body': {'boundary': {'observedSettings': resolved_settings, 'notEstablished': resolved_limits}}}
