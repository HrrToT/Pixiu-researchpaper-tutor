"""Typed answer roles from the existing planner, never paper evidence."""


def enabled(record):
    from services.deep_research.comparison_generation import enabled as cells_enabled
    return (type(record.get('comparisonPlanningContractVersion')) is int
            and (record['comparisonPlanningContractVersion'] in (1,2)
                 or record['comparisonPlanningContractVersion'] in (3,4,5,6)
                 and type(record.get('comparisonReviewBatchContractVersion')) is int
                 and record['comparisonReviewBatchContractVersion'] in (2, 3))
            and type(record.get('factualReviewContractVersion')) is int
            and record['factualReviewContractVersion'] == 4 and cells_enabled(record))


def operations_enabled(record):
    return isinstance(record,dict) and enabled(record) and record['comparisonPlanningContractVersion'] in (2,3,4,5,6)


def synthesis_input_limit(record):
    # A per-request source window, NOT an increase to the run's atomic budget.
    # Frozen v1/legacy requests retain their original window and selection.
    return 32000 if operations_enabled(record) else 24000


def validate_role(obligation, question):
    if not isinstance(obligation,dict) or not isinstance(question,str):
        raise ValueError('Invalid comparison role input')
    if obligation.get('purpose') not in ('answer_requirement','supporting_research'):
        raise ValueError('Invalid comparison obligation purpose')
    role = obligation.get('comparisonRole')
    if (not isinstance(role, dict) or set(role) != {'kind', 'label', 'requestExcerpt'}
            or not isinstance(role['kind'],str) or role['kind'] not in {'per_paper', 'joint', 'supporting'}):
        raise ValueError('Invalid comparison role')
    if (not isinstance(role['label'], str) or not role['label'].strip() or role['label']!=role['label'].strip()
            or len(role['label']) > 80 or any(ord(c) < 32 for c in role['label'])):
        raise ValueError('Invalid comparison axis label')
    excerpt = role['requestExcerpt']
    if not isinstance(excerpt, str) or not excerpt.strip() or excerpt not in question:
        raise ValueError('Comparison role must bind literal user text')
    support = obligation.get('purpose') == 'supporting_research'
    if (role['kind'] == 'supporting') != support:
        raise ValueError('Comparison role conflicts with obligation purpose')
    return role


def validate_plan(plan, question):
    for item in plan:
        for obligation in item.get('obligations', []):
            validate_role(obligation, question)


def bind_selected_pair(obligation, selected):
    """Restore one missing ID only when a typed answer already requests the full pair."""
    requested = obligation.get('requiredSources', [])
    if (obligation.get('purpose') == 'answer_requirement'
            and (obligation.get('comparisonRole') or {}).get('kind') in ('per_paper', 'joint')
            and len(requested) == len(set(requested)) == 2
            and len(set(requested).intersection(selected)) == 1):
        return list(selected)
    return requested


GUIDANCE = '''For this comparison, EVERY obligation also has comparisonRole:
{kind:"per_paper|joint|supporting",label:"short readable axis/judgement",requestExcerpt:"literal user substring"}.
Use per_paper for ONE factual dimension (mechanism, cost, quality/storage, or speed).
Prefer one dimension obligation listing all requested papers, rather than duplicating it per paper.
Keep independently requested dimensions separate; never merge mechanism and cost merely to save items.
Use joint for cross-paper comparability, tradeoffs and conditional choice. It requires a joint
judgement, not another summary of each abstract. Use supporting only with purpose=supporting_research.
The role requestExcerpt may be shorter than eight characters to locate a short requested axis;
the existing obligation requestExcerpt still obeys its original minimum/context rules.
Labels describe answer structure, never guessed facts. Every role binds actual user text.
Required sources, original goals, criteria, 1-4 items and at most2 obligations per item remain.
This role grants no source permission, factual support or completeness approval.'''


def guidance(record):
    from services.deep_research.comparison_joint_reports import enabled,PLANNING
    result = GUIDANCE.replace('Use joint for cross-paper comparability, tradeoffs and conditional choice. It requires a joint\n'
        'judgement, not another summary of each abstract.', PLANNING) if enabled(record) else GUIDANCE
    version = record.get('comparisonPerPaperResultRolesVersion')
    if version in (1, 2):
        result += (' A request for a result and its conditions from EACH paper is one per_paper axis '
                   'with both required papers. A matched comparison or cross-paper judgement is a separate joint axis.')
    if version == 2:
        result += (' When both appear in the same sentence or adjacent sentences, assign separate obligations '
                   'with disjoint literal excerpts. Keep every requested comparison boundary in the joint obligation.')
    return result
