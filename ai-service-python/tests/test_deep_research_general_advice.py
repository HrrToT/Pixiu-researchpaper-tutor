import json
from copy import deepcopy
from unittest.mock import Mock
import pytest
from services.deep_research.general_advice import eligible,enabled
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.verification import make_evidence
from services.deep_research.reporting import render_report,publication_notices,conversation_summary
from services.deep_research.answer_constraints import visible_count


@pytest.mark.parametrize(('text', 'expected'), [
    ('Rendering requires GPU memory for the model and an additional 30–500 MB buffer.', False),
    ('The model file was 45 MB, which can reduce pressure on GPU memory.', False),
    ('Peak GPU memory was estimated at 4 GB.', False),
    ('Peak GPU memory was 4 GB on the evaluation device.', True),
    ('渲染时峰值显存实测为 4 GB。', True),
])
def test_direct_device_memory_excludes_proxies_and_estimates(text, expected):
    from services.deep_research.general_advice import has_device_memory_measurement

    assert has_device_memory_measurement(text, direct=True) is expected


def test_measured_advice_cannot_strip_the_estimate_qualifier_from_its_citation():
    from services.deep_research.general_advice import validate

    excerpt = 'peak GPU memory was 4 GB'
    quote = 'The estimated peak GPU memory was 4 GB.'
    evidence = make_evidence({'workId': 'p', 'versionId': 'v', 'contentHash': 'h', 'accessLevel': 'fulltext'},
                             quote, quote, location={}, obligation_ids=[])
    cid = evidence['evidenceId']
    claim = {'kind': 'proposal', 'text': '显存受限时可考虑此方案。', 'evidenceRefs': [cid]}
    decision = verdict('other_nonexperimental', cid)
    decision['adviceAudit']['deviceMemory'] = {'mode': 'measured',
        'premise': {'evidenceId': cid, 'path': ['quote']}, 'excerpt': excerpt}
    assert validate(claim, decision, [evidence], device_memory=True) == []
    assert validate(claim, decision, [evidence], device_memory=True, direct_device_memory=True) == [
        'device_memory_premise_not_established']


def fixture():
    quote='Pruning reduces count. Distillation reduces feature size.'
    e=make_evidence({'workId':'p','versionId':'v','contentHash':'h','accessLevel':'fulltext'},quote,quote,location={},obligation_ids=[])
    c={'claimId':'c','kind':'proposal','text':'建议先读剪枝，再读蒸馏。','conditions':{},'evidenceRefs':[e['evidenceId']]}
    return c,e


def verdict(purpose='reading_guidance',eid='E1'):
    return {'claimId':'c','status':'passed','reason':'次序与实际方法和阅读目标相符。',
        'adviceAudit':{'purpose':purpose,'targetPath':['text'],'appropriate':True,
        'premises':[{'evidenceId':eid,'path':['quote']}]}}


@pytest.mark.parametrize('revision',[False,True])
def test_advice_and_revisions_use_own_reviewer_and_citations(revision):
    c,e=fixture();before=deepcopy((c,e))
    invoke=Mock(return_value={'content':json.dumps([verdict()])})
    checker=BudgetedSemanticChecker(invoke,'r',general_advice_review=True,research_question='给出阅读顺序')
    result=checker.check_revisions([c],[e],[]) if revision else checker([c],[e])
    assert result[0]['status']=='passed'
    kw=invoke.call_args.kwargs
    assert kw['node']==('verify_repair_advice' if revision else 'verify_advice')
    assert 'NONEXPERIMENTAL recommendations' in kw['prompt'] and e['quote'] in kw['prompt']
    assert 'prospective experimental design' not in kw['prompt']
    assert result[0]['adviceAudit']['premises'][0]['evidenceId']==e['evidenceId']
    assert kw['use_reserve'] is True and (c,e)==before


@pytest.mark.parametrize('change',[
    lambda v:v.pop('adviceAudit'),
    lambda v:v['adviceAudit'].update(purpose='scientific_design'),
    lambda v:v['adviceAudit'].update(targetPath=['conditions']),
    lambda v:v['adviceAudit'].update(appropriate=False),
    lambda v:v['adviceAudit'].update(premises=[]),
    lambda v:v['adviceAudit']['premises'][0].update(evidenceId='foreign'),
    lambda v:v['adviceAudit']['premises'][0].update(path=['missing']),
])
def test_unbound_or_scientific_advice_audit_is_not_accepted(change):
    c,e=fixture();v=verdict();change(v)
    invoke=Mock(return_value={'content':json.dumps([v])})
    result=BudgetedSemanticChecker(invoke,'r',general_advice_review=True)([c],[e])
    assert result[0]['status']=='failed'


def test_old_policy_keeps_original_experiment_review_path():
    c,e=fixture();invoke=Mock(return_value={'content':json.dumps([{'claimId':'c','status':'passed','designAudit':{}}])})
    BudgetedSemanticChecker(invoke,'r')([c],[e])
    assert invoke.call_args.kwargs['node']=='verify_design_science'
    assert 'prospective experimental design' in invoke.call_args.kwargs['prompt']


@pytest.mark.parametrize('revision', [False, True])
@pytest.mark.parametrize('mode, text, quote, approved', [
    (None, '显存受限时优先考虑压缩表示，其文件更小，实际显存需实测。', 'The model file was 45 MB.', False),
    ('measured', '显存受限时优先考虑压缩表示。', 'The model file was 45 MB. GPU memory was not measured.', False),
    ('test_first', '显存受限时优先考虑压缩表示，先实测显存。', 'The model file was 45 MB.', False),
    ('test_first', '文件大小不能证明显存更低，但优先考虑压缩表示，先实测显存。', 'The model file was 45 MB.', False),
    ('test_first', '文件大小不能证明显存更低。先在目标设备测量峰值显存，再按测量结果选择。', 'The model file was 45 MB.', True),
    ('measured', '该设置下实测峰值显存为 4 GB，可在相同设置下考虑该方法。', 'Peak GPU memory was 4 GB on the evaluation device.', True),
])
def test_device_memory_advice_requires_a_bound_measurement_or_test_first(revision, mode, text, quote, approved):
    c, _ = fixture()
    e = make_evidence({'workId': 'p', 'versionId': 'v', 'contentHash': 'h', 'accessLevel': 'fulltext'},
                      quote, quote, location={}, obligation_ids=[])
    c.update(text=text, evidenceRefs=[e['evidenceId']])
    row = verdict(purpose='other_nonexperimental')
    if mode:
        memory = {'mode': mode}
        if mode == 'measured':
            memory.update(premise=deepcopy(row['adviceAudit']['premises'][0]), excerpt=quote)
        row['adviceAudit']['deviceMemory'] = memory
    invoke = Mock(return_value={'content': json.dumps([row])})
    checker = BudgetedSemanticChecker(invoke, 'r', general_advice_review=True, device_memory_advice=True)
    result = checker.check_revisions([c], [e], []) if revision else checker([c], [e])
    assert (result[0]['status'] == 'passed') is approved
    if approved and mode == 'measured':
        assert result[0]['adviceAudit']['deviceMemory']['premise']['evidenceId'] == e['evidenceId']


@pytest.mark.parametrize('field',['designRole','executionSpec','designContractVersion','budgetContractVersion','hypothesisContractVersion','protocolContractVersion','workflowContractVersion'])
def test_formal_or_even_invalid_design_fields_cannot_select_advice_path(field):
    c,_=fixture();c[field]=None
    assert not eligible(c)


@pytest.mark.parametrize('preference, duplicate, approved', [
    ('', False, True),
    (' 仍然推荐采用压缩方案。', False, False),
    ('', True, False),
])
def test_v26_advice_replay_checks_exact_test_first_decision_returned_at_verdict_root(preference, duplicate, approved):
    c, e = fixture()
    c['text'] = ('显存受限时，应先在相同条件下测量两种方法的峰值显存占用，再根据测量结果选择。'
                 '当前引用未提供峰值显存测量，无法直接比较。' + preference)
    row = verdict(purpose='research_navigation')
    row['deviceMemory'] = {'mode': 'test_first'}
    if duplicate:
        row['adviceAudit']['deviceMemory'] = {'mode': 'measured'}
    checker = BudgetedSemanticChecker(Mock(return_value={'content': json.dumps([row])}), 'r',
                                      general_advice_review=True, device_memory_advice=True)
    result = checker([c], [e])[0]
    assert (result['status'] == 'passed') is approved
    if approved:
        assert result['adviceAudit']['deviceMemory'] == {'mode': 'test_first'}
        assert 'deviceMemory' not in result


@pytest.mark.parametrize('version', [2, 3])
def test_v27_deployment_preflight_is_distinguished_from_scientific_design(version):
    c, e = fixture()
    c.update(text='显存受限时，建议先在同一平台和相同数据集上测量两种方法的峰值显存，再按实测结果选择。',
             conditions={'measurement': 'same platform, data, and resolution'})
    row = verdict(purpose='other_nonexperimental')
    row['adviceAudit']['deviceMemory'] = {'mode': 'test_first'}
    invoke = Mock(return_value={'content': json.dumps([row])})
    checker = BudgetedSemanticChecker(invoke, 'r', general_advice_review=True, device_memory_advice=version)
    assert checker([c], [e])[0]['status'] == 'passed'
    prompt = invoke.call_args.kwargs['prompt']
    assert ('deployment preflight: advising' in prompt) is (version == 3)
    assert ('past numeric measurement is not required' in prompt) is (version == 3)
    assert ('even when every cited source lacks a peak-memory value' in prompt) is (version == 3)
    row['adviceAudit']['purpose'] = 'scientific_design'
    invoke.return_value = {'content': json.dumps([row])}
    assert checker([c], [e])[0]['status'] == 'failed'


def test_hypotheses_and_experiment_objectives_keep_scientific_path():
    c,_=fixture();c['kind']='hypothesis';assert not eligible(c)
    assert not enabled({'recommendationReviewContractVersion':1,'state':{'outputKind':'experiment_design'}})
    assert enabled({'recommendationReviewContractVersion':1,'state':{'outputKind':'direction_survey'}})
    assert not enabled({'recommendationReviewContractVersion':True,'state':{'outputKind':'direction_survey'}})


@pytest.mark.parametrize('change, uses_preflight, expected', [
    ('none', True, 'passed'), ('named_preference', False, 'failed'),
    ('paper_condition', False, 'passed'), ('reviewer_rejects', True, 'failed'),
    ('wrong_purpose', True, 'failed'), ('foreign_binding', True, 'failed'),
])
def test_fixed_deployment_preflight_is_reviewed_as_a_future_check(change, uses_preflight, expected):
    from services.deep_research.general_advice import DEVICE_MEMORY_TEST_FIRST_TEXT

    claim, evidence = fixture()
    claim['text'] = DEVICE_MEMORY_TEST_FIRST_TEXT
    answer = verdict(purpose='other_nonexperimental')
    answer['adviceAudit']['deviceMemory'] = {'mode': 'test_first'}
    if change == 'named_preference':
        claim['text'] += '优先采用压缩方案。'
    elif change == 'paper_condition':
        claim['conditions'] = {'premise': 'Pruning reduces count.'}
    elif change == 'reviewer_rejects':
        answer.update(status='failed', reason='该用户问题要求解释原理，这个部署检查未回答所问。')
    elif change == 'wrong_purpose':
        answer['adviceAudit']['purpose'] = 'reading_guidance'
    elif change == 'foreign_binding':
        answer['adviceAudit']['premises'][0]['evidenceId'] = 'unowned'
    invoke = Mock(return_value={'content': json.dumps([answer], ensure_ascii=False)})
    checker = BudgetedSemanticChecker(invoke, 'r', general_advice_review=True, device_memory_advice=4,
                                      research_question='显存受限时如何选择方法？')
    result, = checker([claim], [evidence])
    invoke.assert_called_once()
    request = invoke.call_args.kwargs['prompt']
    assert request.startswith('Review whether the proposed deployment check') == uses_preflight
    assert ('A prior peak-memory number is not a' in request) == uses_preflight
    assert evidence['quote'] in request
    assert result['status'] == expected


def test_mixed_deployment_and_reading_advice_receive_distinct_checks_in_same_call():
    from services.deep_research.general_advice import DEVICE_MEMORY_TEST_FIRST_TEXT

    reading, evidence = fixture()
    preflight = {**reading, 'claimId': 'deployment', 'text': DEVICE_MEMORY_TEST_FIRST_TEXT}
    recommendation = verdict(purpose='other_nonexperimental')
    recommendation['claimId'] = 'deployment'
    recommendation['adviceAudit']['deviceMemory'] = {'mode': 'test_first'}
    invoke = Mock(return_value={'content': json.dumps([verdict(), recommendation], ensure_ascii=False)})
    checker = BudgetedSemanticChecker(invoke, 'r', general_advice_review=True, device_memory_advice=4)
    assert [row['status'] for row in checker([reading, preflight], [evidence])] == ['passed', 'passed']
    invoke.assert_called_once()
    request = invoke.call_args.kwargs['prompt']
    assert request.startswith('Review the actual targets as NONEXPERIMENTAL')
    assert 'Deployment preflight target IDs: ["deployment"]' in request


def test_over_capacity_own_evidence_is_not_cut_or_dispatched():
    c,e=fixture();e['quote']='x'*25000;invoke=Mock()
    result=BudgetedSemanticChecker(invoke,'r',general_advice_review=True)([c],[e])
    assert result[0]['status']=='failed' and result[0]['executionState']=='not_started'
    invoke.assert_not_called()


def test_presentation_keeps_advice_clear_and_experiments_explicit_without_changing_claims():
    c,e=fixture();before=deepcopy((c,e))
    visible,folded=publication_notices([c],presentation_version=3,output_kind='direction_survey')
    payload={'claims':[c],'evidence':[e],'outputKind':'direction_survey','sections':[{'title':'推荐阅读顺序','claimIds':['c']}],
        'presentationVersion':3,'characterLimit':300,'limitations':visible,'verificationNotice':folded}
    body=render_report(payload);summary=conversation_summary([c],'complete',evidence=[e],output_kind='direction_survey',presentation_version=3)
    assert '实验建议' not in body+summary and '未经实验验证' not in body+summary
    assert '建议阅读顺序' not in body # preserve original wording, do not manufacture it
    assert c['text'] in body and c['text'] in summary and (c,e)==before
    old=render_report({**payload,'presentationVersion':2})
    assert '实验建议：' in old
    assert publication_notices([c],presentation_version=2)[0]
    assert publication_notices([c],presentation_version=3,output_kind='experiment_design')[0]
    assert visible_count({'claims':[c],'sections':payload['sections']},300,'direction_survey',[e],3)>len(c['text'])


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_advice_policy_is_server_owned_immutable_and_absent_on_legacy(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'给出阅读顺序','deferStart':True,
            'recommendationReviewContractVersion':replacement},start_async=False)
        assert run['recommendationReviewContractVersion']==2
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'recommendationReviewContractVersion':1 if replacement == 2 else replacement})
        assert not enabled({'state':{'outputKind':'direction_survey'}})
    finally:facade.shutdown()


def test_advice_nodes_keep_json_capacity_and_finalization_registration():
    from services.deep_research.structured_output import ARRAY_NODES,DESIGN_REVIEW_NODES
    from services.deep_research.verification_capacity import has_verification_input_contract
    from services.deep_research.finalization_pool import _FINALIZATION_NODES
    for node in ('verify_advice','verify_repair_advice'):
        assert node in ARRAY_NODES and node not in DESIGN_REVIEW_NODES and node in _FINALIZATION_NODES
        assert has_verification_input_contract({'verificationInputContractVersion':1},node)
