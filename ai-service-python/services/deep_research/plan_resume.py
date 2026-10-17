"""Reassess saved evidence after a human plan edit, without replaying the old draft."""
from copy import deepcopy

from services.deep_research.contracts import DeepResearchError, utc_now_iso
from services.deep_research.obligation_binding import eligible_obligation_ids


def enabled(record):
    return type(record.get('planResumeContractVersion')) is int and record['planResumeContractVersion'] == 1


def retire_outputs(state, new_plan, revision):
    state = deepcopy(state)
    retired = {key: state.pop(key) for key in list(state)
               if key.startswith(('repair', 'report', 'initialVerification', 'initialAnswerCoverage'))
               or key in {'verifiedReport', 'audienceRewrite', 'synthesisContainer', 'coverage', 'gaps',
                          'stopReason', 'assessmentStatus', 'publicationId'}}
    history = state.setdefault('planEditHistory', [])
    history.append({'planRevision': revision, 'plan': state.get('plan', []),
                    'retiredOutputs': retired, 'editedAt': utc_now_iso()})
    obligations = {o['obligationId']: o for item in new_plan for o in item['obligations']}
    state['sources'] = [{**s, 'obligationIds': eligible_obligation_ids(s, obligations)}
                        for s in state.get('sources', [])]
    state['evidence'] = [{**e, 'obligationIds': eligible_obligation_ids({
        'workId': e.get('sourceWorkId'), 'versionId': e.get('sourceVersionId'),
        'ownerMaterialId': e.get('ownerMaterialId')}, obligations),
        'verification': {**e.get('verification', {}), 'semantic': 'unchecked'}}
        for e in state.get('evidence', [])]
    state['editedPlanRevision'] = revision + 1
    return state


def checkpoint_patch(record, checkpoint):
    domain = record.get('state') or {}
    revision = domain.get('editedPlanRevision')
    if not enabled(record) or type(revision) is not int or revision < 1:
        return None
    if revision != domain.get('planRevision'):
        raise DeepResearchError('invalid_plan_resume', '保存的计划版本与恢复版本不一致。')
    previous = (checkpoint or {}).get('channel_values', {}).get('plan_revision', 0)
    if previous == revision:
        return None
    return {'plan_revision': revision, 'plan_ids': [i['itemId'] for i in domain['plan']],
            'source_ids': [s['sourceId'] for s in domain.get('sources', [])],
            'evidence_ids': [e['evidenceId'] for e in domain.get('evidence', [])],
            'claim_ids': [], 'coverage_state': {}, 'gaps': [], 'requery_count': 0, 'requery_queries': [],
            'budget_exhausted': False, 'stop_reason': '', 'error_code': '', 'outcome': 'none',
            'report_version_id': '', 'publication_id': '', 'prev_source_count': 0,
            'clarification_needed': False, 'clarification_question': '', 'refresh_brief': False,
            'prev_assessment_evidence_digest': '', 'assess_after_extraction_stop': False,
            'assess_inherited': bool(domain.get('evidence'))}


def edited_question_context(record):
    domain = record.get('state') or {}
    if not enabled(record) or not domain.get('editedPlanRevision'):
        return ''
    rows = []
    for item in domain.get('plan', []):
        rows.append(item['question'])
        rows.extend(o['question'] for o in item['obligations'])
    return '\n'.join(dict.fromkeys(rows))
