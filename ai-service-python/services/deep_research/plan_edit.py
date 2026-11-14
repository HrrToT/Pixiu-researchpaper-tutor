"""Validate plan-edit revisions and source identities within the frozen policy."""
from services.deep_research.contracts import DeepResearchError


def require_plan_revision(record, payload):
    current = (record.get('state') or {}).get('planRevision', 0)
    if type(current) is not int or current < 0:
        raise DeepResearchError('invalid_plan_revision', '保存的计划版本无效，请检查研究记录。')
    required = type(record.get('planEditContractVersion')) is int and record['planEditContractVersion'] == 1
    if 'planRevision' not in payload:
        if required:
            raise DeepResearchError('invalid_plan_revision', '请提供当前计划版本后再提交修改。', {'status_code': 422})
        return current
    expected = payload['planRevision']
    if type(expected) is not int or expected < 0:
        raise DeepResearchError('invalid_plan_revision', '计划版本必须是非负整数。', {'status_code': 422})
    if expected != current:
        raise DeepResearchError('plan_revision_conflict', '计划已更新，请刷新后再修改。',
                                {'status_code': 409, 'expected': expected, 'actual': current})
    return current


def source_allowed(record, identity):
    if not isinstance(identity, str):
        return False
    if identity in {m['materialId'] for m in record.get('materials', [])}:
        return True
    if record.get('sourcePolicy', {}).get('mode') not in {'academic_external', 'external_only'}:
        return False
    if not identity.startswith('arxiv:'):
        return False
    from services.deep_research_academic import checked_arxiv_id
    try:
        checked_arxiv_id(identity[len('arxiv:'):])
    except ValueError:
        return False
    # A public identifier is still fetched only by the existing fixed-host
    # provider and admitted by the original policy, scope checks and budget.
    return True
