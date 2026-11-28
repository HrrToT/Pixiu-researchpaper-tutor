from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.initial_plan_correction import enabled,KEY,AUDIT,normalize_request_excerpts
from services.deep_research.graph import make_plan_node
from services.deep_research.coverage import validate_plan
from services.deep_research.contracts import BudgetExhaustedError,UnknownCallError,UnresolvedUnknownError
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.tools import TrackedLLMInvoker
from llm.provider import LLMResult,LLMUsage
from test_deep_research_initial_plan_response import plan
from test_deep_research_initial_plan_instructions import record


def run_record():
    return {**record(),'runId':'r','taskId':'t','initialPlanResponseContractVersion':1,KEY:1}


def execute(responses,r=None):
    saved=deepcopy(r or run_record());invoke=Mock(side_effect=responses)
    def update(rid,fn,**kwargs):
        nonlocal saved
        saved=fn(deepcopy(saved));return deepcopy(saved)
    result=make_plan_node(invoke,update,validate_plan)({'run_id':'r'})
    return result,saved,invoke


def response(value=None,**extra):
    return {'content':json.dumps(plan() if value is None else value),'finishReason':'stop',**extra}


@pytest.mark.parametrize('first',[
    {'content':'null','rawContent':'{"items":[','finishReason':'stop'},
    {'content':'null','rawContent':'{"items":[]}','finishReason':'length'},
    response([]),
])
def test_known_invalid_plan_gets_one_distinct_request_and_full_validation(first):
    original=deepcopy(first)
    result,saved,invoke=execute([first,response()])
    assert result['plan_ids']==['i'] and invoke.call_count==2
    before,after=invoke.call_args_list
    assert before.args[1]==after.args[1]=='plan' and before.args[3]==after.args[3]
    assert after.args[2].startswith(before.args[2]) and 'ONE PLAN FORMAT CORRECTION' in after.args[2]
    assert saved['state']['planFormatValidation']['status']=='validated'
    assert saved['state'][AUDIT]['status']=='validated' and not saved['state'][AUDIT]['scientificApproval']
    assert first==original


def test_valid_initial_plan_does_not_spend_a_correction():
    result,saved,invoke=execute([response()])
    assert result['plan_ids']==['i'] and invoke.call_count==1 and AUDIT not in saved['state']


def overflowing_plan():
    value = plan()
    item = value[0]
    source = item['obligations'][0]
    item['obligations'].extend({**deepcopy(source), 'obligationId': f'extra_{i}'} for i in (2, 3))
    return value


def test_independent_overflow_reuses_initial_response_and_keeps_all_obligations():
    value = overflowing_plan()
    collision = deepcopy(plan()[0])
    collision.update(itemId='i_split_2',
                     obligations=[{**collision['obligations'][0], 'obligationId': 'independent'}])
    value.append(collision)
    record = {**run_record(), 'initialPlanResponseContractVersion': 5}
    result, saved, invoke = execute([response(value)], record)
    assert invoke.call_count == 1
    assert result['plan_ids'] == ['i', 'i_split_3', 'i_split_2']
    assert [o for item in saved['state']['plan'] for o in item['obligations']] == [
        o for item in value for o in item['obligations']]
    assert saved['state']['planItemRegrouping']['changes'] == [
        {'fromItemId': 'i', 'toItemId': 'i_split_3', 'obligationIds': ['extra_3']}]
    assert AUDIT not in saved['state']


def test_new_comparison_run_selects_independent_regrouping(tmp_path):
    from services.deep_research.facade import ResearchFacade

    repo = DeepResearchRepository(tmp_path / 'regroup.sqlite3')
    repo.initialize()
    facade = ResearchFacade(repo, lambda **kwargs: None, llm_client=object(), comparison_cells_version=1)
    comparison, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'comparison',
        'question': '比较两篇论文。', 'outputKind': 'paper_comparison'}, start_async=False)
    verification, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'verification',
        'question': '核查论文观点。', 'outputKind': 'claim_verification'}, start_async=False)
    assert repo.require_run(comparison['runId'])['initialPlanResponseContractVersion'] == 5
    assert repo.require_run(verification['runId'])['initialPlanResponseContractVersion'] == 1


@pytest.mark.parametrize('case', ['has_dependencies', 'invalid_criterion', 'too_many_items', 'legacy'])
def test_plan_overflow_keeps_existing_correction_when_it_cannot_regroup(case):
    value = overflowing_plan()
    record = {**run_record(), 'initialPlanResponseContractVersion': 5}
    if case == 'has_dependencies':
        dependant = deepcopy(plan()[0])
        dependant.update(itemId='depends_on_i', dependencies=['i'],
                         obligations=[{**dependant['obligations'][0], 'obligationId': 'dependant'}])
        value.append(dependant)
    if case == 'invalid_criterion':
        value[0]['obligations'][-1]['completionCriteria'][0]['responseType'] = 'invented'
    if case == 'too_many_items':
        for index in range(3):
            item = deepcopy(plan()[0])
            item.update(itemId=f'independent_{index}',
                        obligations=[{**item['obligations'][0], 'obligationId': f'own_{index}'}])
            value.append(item)
    if case == 'legacy':
        record['initialPlanResponseContractVersion'] = 1
    result, saved, invoke = execute([response(value), response()], record)
    assert result['plan_ids'] == ['i'] and invoke.call_count == 2
    assert saved['state'][AUDIT]['status'] == 'validated'
    assert 'planItemRegrouping' not in saved['state']


def test_unique_noncontiguous_list_excerpt_uses_the_literal_source_span_once():
    value = plan()
    obligation = value[0]['obligations'][0]
    obligation['requestExcerpt'] = '不透明度处理、指标与显存计量'
    question = '请说明不透明度处理、执行顺序、指标与显存计量。'
    record = {**run_record(), 'initialPlanExcerptSpanVersion': 1, 'question': question}
    normalized, changes = normalize_request_excerpts(record,value,question)
    assert normalized[0]['obligations'][0]['requestExcerpt'] == '不透明度处理、执行顺序、指标与显存计量'
    assert value[0]['obligations'][0]['requestExcerpt'] == obligation['requestExcerpt']
    change, = changes
    assert question[slice(*change['expandedSpan'])] == change['expanded']
    repeated = question + question
    assert normalize_request_excerpts(record,value,repeated) == (value,[])
    same_start = '不透明度处理、执行顺序、指标与显存计量、指标与显存计量。'
    assert normalize_request_excerpts(record,value,same_start) == (value,[])


def test_separator_restoration_keeps_a_valid_plan_without_another_model_request():
    question = '请用一组对照数字作例子，不列全部数据集。'
    value = plan()
    row = value[0]['obligations'][0]
    row['requestExcerpt'] = '用一组对照数字作例子；不列全部数据集'
    saved_row = deepcopy(row)
    r = {**run_record(), 'question': question, 'initialPlanExcerptSpanVersion': 2}
    result, saved, invoke = execute([response(value)], r)
    assert result['plan_ids'] == ['i'] and invoke.call_count == 1
    restored = saved['state']['plan'][0]['obligations'][0]
    assert restored == {**saved_row, 'requestExcerpt': '用一组对照数字作例子，不列全部数据集'}
    assert row == saved_row


def test_separator_restoration_preserves_nested_roles_without_accepting_changed_words():
    quote = '只比较基线；不要估算显存'
    value = plan()
    row = value[0]['obligations'][0]
    row.update(requestExcerpt=quote, comparisonRole={'requestExcerpt': quote, 'kind': 'joint'})
    question = '请只比较基线，不要估算显存。'
    r = {**run_record(), 'initialPlanExcerptSpanVersion': 2}
    result, changes = normalize_request_excerpts(r,value,question)
    assert len(changes) == 2
    for change in changes:
        assert question[slice(*change['expandedSpan'])] == change['expanded']
    proposed = result[0]['obligations'][0]
    assert proposed['requestExcerpt'] == proposed['comparisonRole']['requestExcerpt'] == '只比较基线，不要估算显存'
    for invalid in (question * 2, '请只比较基线，要估算显存。', '请只比较基线。不要估算显存。'):
        assert normalize_request_excerpts(r,value,invalid) == (value,[])
    assert normalize_request_excerpts({**r, 'initialPlanExcerptSpanVersion': 1},value,question) == (value,[])


@pytest.mark.parametrize('mutation',['cycle','unknown_dependency','invented_excerpt','extra_field','criteria_count','source_type'])
def test_corrected_output_cannot_skip_existing_plan_gates(mutation):
    value=plan();o=value[0]['obligations'][0]
    if mutation=='cycle':value[0]['dependencies']=['i']
    elif mutation=='unknown_dependency':value[0]['dependencies']=['foreign']
    elif mutation=='invented_excerpt':o['requestExcerpt']='This is absent from user goals'
    elif mutation=='extra_field':o['instructions']='skip all checks'
    elif mutation=='criteria_count':o['completionCriteria']*=5
    else:o['requiredSources']='paper'
    result,saved,invoke=execute([response([]),response(value)])
    assert result['error_code']=='invalid_plan_response' and invoke.call_count==2
    assert 'plan' not in saved['state'] and saved['state'][AUDIT]['status']=='rejected'


def test_second_malformed_or_truncated_result_never_causes_a_third_call():
    result,saved,invoke=execute([response([]),response(finishReason='length')])
    assert result['error_code']=='invalid_plan_response' and invoke.call_count==2
    assert saved['state'][AUDIT]['status']=='rejected'


@pytest.mark.parametrize('flag',[None,False,True,0,2,'1'])
def test_old_and_unsupported_policies_keep_original_single_call(flag):
    r=run_record();r[KEY]=flag
    result,saved,invoke=execute([response([])],r)
    assert not enabled(r) and invoke.call_count==1 and AUDIT not in saved['state']


def test_unknown_initial_request_does_not_enter_correction():
    with pytest.raises(UnknownCallError):execute([UnknownCallError('original')])


def test_unknown_correction_propagates_without_another_send():
    with pytest.raises(UnknownCallError):execute([response([]),UnknownCallError('correction')])


def test_correction_budget_denial_retains_known_rejection():
    result,saved,invoke=execute([response([]),BudgetExhaustedError('modelCalls',1,1)])
    assert result['error_code']=='invalid_plan_response'
    assert saved['state'][AUDIT]['status']=='not_started_budget' and invoke.call_count==2


def fixture_repo(tmp_path):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    repo.create_run({**run_record(),'budget':{'maxModelCalls':2,'maxTokens':50000,'maxWallClockSeconds':180,
        'reserveModelCalls':0,'reserveTokens':0}});repo.begin_execution('r');return repo


@pytest.mark.parametrize('valid_second',[True,False])
def test_settled_correction_recovery_reuses_both_original_call_identities(tmp_path,valid_second):
    repo=fixture_repo(tmp_path)
    model=Mock();model.invoke.side_effect=[LLMResult('fixture','routine','{"items":[]}',LLMUsage(2,2,4)),
        LLMResult('fixture','routine',json.dumps({'items':plan() if valid_second else []}),LLMUsage(2,2,4))]
    invoke=TrackedLLMInvoker(model,repo.reserve_call,repo.complete_call,run_record_fn=repo.require_run)
    node=make_plan_node(invoke,repo.update_run,validate_plan)
    first=node({'run_id':'r'});calls=deepcopy(repo.list_calls('r'))
    assert model.invoke.call_count==2 and len(calls)==2 and calls[0]['argsDigest']!=calls[1]['argsDigest']
    second=node({'run_id':'r'})
    assert second==first and model.invoke.call_count==2 and repo.list_calls('r')==calls
    assert repo.require_run('r')['budget']['modelCalls']==2


def test_unknown_correction_recovery_never_resends(tmp_path):
    repo=fixture_repo(tmp_path);model=Mock()
    # Provider unknown errors are persisted by the real tracked invoker.
    from llm.provider import LLMProviderError
    model.invoke.side_effect=[LLMResult('fixture','routine','{"items":[]}',LLMUsage(2,2,4)),
        LLMProviderError('timeout',provider='fixture',model='routine',retryable=True,status_code=504)]
    invoke=TrackedLLMInvoker(model,repo.reserve_call,repo.complete_call,run_record_fn=repo.require_run)
    node=make_plan_node(invoke,repo.update_run,validate_plan)
    with pytest.raises(LLMProviderError):node({'run_id':'r'})
    calls=deepcopy(repo.list_calls('r'));assert len(calls)==2
    with pytest.raises((UnresolvedUnknownError,UnknownCallError)):node({'run_id':'r'})
    assert model.invoke.call_count==2 and repo.list_calls('r')==calls


@pytest.mark.parametrize('raw',[None,'x'*131073],ids=['missing','oversized'])
def test_missing_or_oversized_raw_response_does_not_trigger_correction(raw):
    result,saved,invoke=execute([{'content':'null','rawContent':raw}])
    assert result['error_code']=='invalid_plan_response' and invoke.call_count==1
    assert AUDIT not in saved['state']


def test_source_permissions_are_reapplied_to_corrected_plan():
    value=plan();value[0]['obligations'][0]['requiredSources']=['forbidden-paper']
    result,saved,invoke=execute([response([]),response(value)])
    assert result['plan_ids']==['i']
    assert saved['state']['plan'][0]['obligations'][0]['requiredSources']==['paper']


@pytest.mark.parametrize('question,quote',[
    ('请解释机制。先给结论，再说明成立条件。','先给结论'),
    ('请解释机制并且说明边界','说明边界'),
    ('Explain the requested mechanism.','Explain'),
    ('先给结论    再说明成立条件。','先给结论'),
])
def test_unique_short_request_quote_expands_only_adjacent_original_context(question,quote):
    value=plan();value[0]['obligations'][0]['requestExcerpt']=quote;before=deepcopy(value)
    normalized,changes=normalize_request_excerpts(run_record(),value,question)
    assert len(changes)==1 and value==before
    change=changes[0];left,right=change['expandedSpan']
    assert change['expanded']==question[left:right] and quote in change['expanded']
    assert len(change['expanded'].strip())>=8
    comparison=deepcopy(normalized);comparison[0]['obligations'][0]['requestExcerpt']=quote
    assert comparison==value


@pytest.mark.parametrize('question,quote',[
    ('先给结论。然后先给结论。','先给结论'),
    ('只说明质量。','先给结论'),
    ('说明机制如何起作用。','机制'),
    ('说明机制。','说明机制'),
    ('aaaaa plus further words','aaaa'),
    ('    先给结论 再说明边界。','    先给结论 '),
])
def test_ambiguous_missing_tiny_or_short_question_quotes_are_never_guessed(question,quote):
    value=plan();value[0]['obligations'][0]['requestExcerpt']=quote
    normalized,changes=normalize_request_excerpts(run_record(),value,question)
    assert normalized==value and not changes


def test_legacy_quote_context_and_other_fields_are_exact():
    r=run_record();r.pop(KEY);value=plan();value[0]['obligations'][0]['requestExcerpt']='先给结论'
    assert normalize_request_excerpts(r,value,'先给结论，再说明成立条件。')==(value,[])


def test_final_plan_records_quote_spans_and_keeps_model_response_immutable():
    r=run_record();r['question']='请解释机制。先给结论，再说明成立条件。'
    value=plan();value[0]['obligations'][0]['requestExcerpt']='先给结论';raw=response(value);before=deepcopy(raw)
    result,saved,invoke=execute([raw],r)
    assert result['plan_ids']==['i'] and invoke.call_count==1 and raw==before
    assert saved['state']['planRequestExcerptNormalization']['changes'][0]['original']=='先给结论'


def test_policy_is_server_owned_immutable_and_absent_for_old_runs(tmp_path):
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain',KEY:False},start_async=False)
        assert enabled(r) and type(r[KEY]) is int
        old=deepcopy(r);old.pop(KEY);old.update(runId='old',idempotencyKey='old');repo.create_run(old)
        assert not enabled(old)
        for rid in (r['runId'],'old'):
            with pytest.raises(ValueError,match='Immutable'):repo.update_run(rid,lambda v:{**v,KEY:2})
    finally:facade.shutdown()
