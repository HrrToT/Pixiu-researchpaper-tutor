from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.completion_criteria import validate_completion_criteria
from services.deep_research.coverage import validate_plan
from services.deep_research.final_coverage import audit_final_answer
from services.deep_research.graph import make_plan_node, make_publish_node
from services.deep_research.coverage_repair import prepare_coverage_repair
from services.deep_research.completion_criteria import revalidate_completion_audit


def plan():
    return [{'itemId': 'p', 'question': 'Explain calibrated matching', 'obligations': [{
        'obligationId': 'o', 'question': 'How do calibrated cameras help matching?',
        'requiredSources': ['paper'], 'completionCriteria': [
            {'criterionId': 'role', 'requirement': '解释相机信息如何约束跨视图匹配位置。', 'responseType': 'explanation'},
            {'criterionId': 'depth', 'requirement': '解释深度如何用于定位三维中心。', 'responseType': 'explanation'}]}]}]


TEXT = '相机几何把候选深度投影到另一视图的对应位置，匹配这些位置的图像特征；深度沿像素射线确定三维中心。'
CLAIMS = [{'claimId': 'c', 'text': TEXT, 'kind': 'reported', 'evidenceRefs': ['e'], 'obligationIds': ['o']}]
EVIDENCE = [{'evidenceId': 'e', 'sourceWorkId': 'paper', 'quote': 'Calibrated cameras warp candidates for matching and unproject depth.'}]


def verdicts():
    binding = [{'claimId': 'c', 'field': 'text'}]
    aspect = {'aspectId': 'mechanism', 'requirement': '解释匹配和定位', 'status': 'covered',
              'basis': {'kind': 'source', 'evidenceId': 'e', 'field': 'quote'}, 'bindings': binding}
    return [{'obligationId': 'o', 'status': 'covered', 'bindings': binding, 'aspects': [aspect],
             'criteria': [{'criterionId': c['criterionId'], 'responseType': c['responseType'],
                           'status': 'covered', 'bindings': binding} for c in plan()[0]['obligations'][0]['completionCriteria']]},
            {'obligationId': 'answer_scope', 'status': 'covered', 'bindings': binding, 'aspects': [aspect]}]


def audit(rows, research_plan=None):
    invoke = Mock(return_value={'content': json.dumps(rows)})
    result = audit_final_answer('r', 'Explain matching and depth to a beginner',
        research_plan or plan(), CLAIMS, EVIDENCE, invoke, json.loads)
    invoke.assert_called_once()
    return result


def test_all_frozen_criteria_need_current_answer_bindings_without_extra_model_calls():
    original = deepcopy((plan(), CLAIMS, EVIDENCE))
    result = audit(verdicts())
    assert result['status'] == 'checked' and not result['gaps']
    assert (plan(), CLAIMS, EVIDENCE) == original


@pytest.mark.parametrize('change', ['absent', 'missing', 'duplicate', 'unknown', 'downgrade',
    'invented_answer', 'source_as_answer', 'foreign_claim', 'bad_field', 'bad_identity'])
def test_overall_covered_cannot_skip_or_downgrade_a_planned_explanation(change):
    rows = verdicts()
    criteria = rows[0]['criteria']
    if change == 'absent': rows[0].pop('criteria')
    elif change == 'missing': criteria.pop()
    elif change == 'duplicate': criteria.append(deepcopy(criteria[0]))
    elif change == 'unknown': criteria.append({**criteria[0], 'criterionId': 'easier_target'})
    elif change == 'downgrade': criteria[0]['responseType'] = 'identification'
    elif change == 'invented_answer': criteria[0]['bindings'] = [{'claimId': 'c', 'excerpt': 'not in the answer'}]
    elif change == 'source_as_answer': criteria[0]['bindings'] = [{'claimId': 'c', 'excerpt': EVIDENCE[0]['quote']}]
    elif change == 'foreign_claim': criteria[0]['bindings'] = [{'claimId': 'unknown', 'field': 'text'}]
    elif change == 'bad_field': criteria[0]['bindings'] = [{'claimId': 'c', 'field': 'text', 'excerpt': TEXT}]
    elif change == 'bad_identity': criteria[0]['criterionId'] = []
    result = audit(rows)
    assert result['verdicts'][0]['status'] == 'partial'
    assert [g['obligationId'] for g in result['gaps']] == ['o']
    assert result['gaps'][0]['missingAspects']
    repair = prepare_coverage_repair({'claims': CLAIMS}, {'accepted': CLAIMS, 'rejected': []}, result)
    assert not repair['accepted'] and repair['rejected'][0]['reason'] == 'answer_incomplete'
    assert all(c['requirement'] in str(repair) for c in plan()[0]['obligations'][0]['completionCriteria']
               if c['requirement'] in result['gaps'][0]['missingAspects'])


def test_legacy_plan_has_no_new_required_audit_fields():
    legacy = plan()
    legacy[0]['obligations'][0].pop('completionCriteria')
    rows = verdicts()
    rows[0].pop('criteria')
    assert not audit(rows, legacy)['gaps']
    validate_completion_criteria(legacy)
    with pytest.raises(ValueError):
        validate_completion_criteria(legacy, required=True)


@pytest.mark.parametrize('change', ['requirements', 'question', 'answer', 'absent_digest', 'missing_criterion'])
def test_resumed_publication_cannot_reuse_a_stale_criteria_decision(change):
    research_plan, claims = plan(), deepcopy(CLAIMS)
    result = audit(verdicts())
    assert revalidate_completion_audit(research_plan, claims, result) == result
    if change == 'requirements': research_plan[0]['obligations'][0]['completionCriteria'][0]['requirement'] = 'Explain a new requirement'
    elif change == 'question': research_plan[0]['obligations'][0]['question'] = 'A different question'
    elif change == 'answer': claims[0]['text'] = 'Names only: cameras, depths, centers.'
    elif change == 'absent_digest': result.pop('completionContractDigest')
    elif change == 'missing_criterion': result['verdicts'][0]['criteria'].pop()
    checked = revalidate_completion_audit(research_plan, claims, result)
    assert checked['status'] == 'invalidated_completion_contract'
    assert checked['gaps'] and checked['gaps'][0]['stage'] == 'answer'


@pytest.mark.parametrize('change', [[], None, [{'criterionId': 'x', 'requirement': 'Explain', 'responseType': []}],
    [{'criterionId': [], 'requirement': 'Explain', 'responseType': 'explanation'}]])
def test_malformed_plan_criteria_fail_before_retrieval(change):
    value = plan()
    value[0]['obligations'][0]['completionCriteria'] = change
    with pytest.raises(ValueError):
        validate_completion_criteria(value, required=True)


def test_new_planner_cannot_persist_an_answer_without_predeclared_requirements():
    record = {'question': 'Explain to a beginner', 'planCompletionContractVersion': 1,
              'state': {'outputKind': 'claim_verification'}, 'materials': [{'materialId': 'paper'}]}
    def update(run, mutate, **kwargs):
        nonlocal record
        record = mutate(record)
        return deepcopy(record)
    legacy = plan()
    legacy[0]['obligations'][0].pop('completionCriteria')
    response = Mock(return_value={'content': json.dumps(legacy)})
    result = make_plan_node(response, update, validate_plan)({'run_id': 'r'})
    assert result['error_code'] == 'invalid_plan_response'
    assert 'plan' not in record['state']
    response.return_value = {'content': json.dumps(plan())}
    result = make_plan_node(response, update, validate_plan)({'run_id': 'r'})
    assert result['plan_ids'] == ['p']
    assert record['state']['plan'][0]['obligations'][0]['completionCriteria'] == plan()[0]['obligations'][0]['completionCriteria']


def test_publish_after_requirement_edit_preserves_answer_but_reports_partial_without_generation():
    result = audit(verdicts())
    edited = plan()
    edited[0]['obligations'][0]['completionCriteria'][0]['requirement'] = 'Explain an additional causal relationship'
    record = {'question': 'Explain matching', 'state': {'plan': edited, 'evidence': EVIDENCE,
        'outputKind': 'claim_verification', 'verifiedReport': {'verifiedClaims': CLAIMS,
            'rejectedClaims': [], 'answerCoverage': result}}}
    def update(run, mutate, **kwargs):
        nonlocal record
        record = mutate(record)
        return deepcopy(record)
    publish = Mock(return_value=({'publicationId': 'pub'}, True))
    outcome = make_publish_node(publish, update)({'run_id': 'r'})
    assert outcome['outcome'] == 'partial'
    assert record['state']['verifiedReport']['answerCoverage']['status'] == 'invalidated_completion_contract'
    payload = publish.call_args.kwargs['payload']
    assert payload['claims'] == CLAIMS and payload['gaps'][0]['stage'] == 'answer'


def test_plan_edit_cannot_silently_remove_new_run_requirements(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.contracts import DeepResearchError
    repo = DeepResearchRepository(str(tmp_path/'research.sqlite3'))
    repo.initialize()
    record, _ = repo.create_run({'runId': 'r', 'taskId': 't', 'question': 'Explain matching',
        'planCompletionContractVersion': 1, 'materials': [{'materialId': 'paper'}], 'state': {'plan': plan()}})
    repo.begin_execution('r')
    paused = repo.transition('r', 'paused')
    facade = ResearchFacade(repo, lambda **kwargs: None, scope_validator=lambda *args: True)
    try:
        edited = plan()
        edited[0]['obligations'][0].pop('completionCriteria')
        with pytest.raises(DeepResearchError) as caught:
            facade._action_plan('r', paused['runRevision'], {'plan': edited})
        assert caught.value.code == 'invalid_plan'
        assert repo.require_run('r')['state']['plan'] == plan()
        revised = plan()
        revised[0]['obligations'][0]['completionCriteria'][0]['requirement'] = '解释新的关系'
        result = facade._action_plan('r', paused['runRevision'], {'plan': revised})
        assert result['plan'][0]['obligations'][0]['completionCriteria'][0]['requirement'] == '解释新的关系'
    finally:
        facade.shutdown()
