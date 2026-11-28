from copy import deepcopy
import json
import re
from unittest.mock import Mock

import pytest

from services.deep_research.comparison_review_batches import MARKER,enabled,groups
from services.deep_research.contracts import UnknownCallError
from services.deep_research.tools import BudgetedSemanticChecker


def inputs(count=3):
    claims=[{'claimId':f'c{i}','kind':'reported','text':f'Method {chr(65+i)} retains quality.',
             'conditions':{},'evidenceRefs':[f'own{i}']} for i in range(count)]
    evidence=[{'evidenceId':f'own{i}','quote':c['text'],'sourceWorkId':f'paper{i}',
               'sourceVersionId':'v','sourceContext':f'Context. {c["text"]} Qualification.'}
              for i,c in enumerate(claims)]
    return claims,evidence


def response(key,index):
    return {'claimId':key,'reason':'Own observation supports this bounded target.',
            'scopeAudit':{'claimStrength':'bounded','evidenceStrength':'bounded','supported':True,
                'statementPath':['text'],'premises':[{'evidenceId':f'E{index+1}','path':['quote']}]}}


def checker(invoke,active=True):
    c=BudgetedSemanticChecker(invoke,'r',single_factual_decision=True,factual_scope=True,
        complete_factual_scope=True,isolate_factual_claims=True,audit_source_fields=True,
        audit_target_fields=True,scope_source_paths=True)
    c._comparison_review_batches=active
    return c


def test_three_targets_use_one_request_with_all_own_evidence_and_normal_validation():
    claims,evidence=inputs();before=deepcopy((claims,evidence))
    invoke=Mock(return_value={'content':json.dumps([response(c['claimId'],i) for i,c in enumerate(claims)])})
    result=checker(invoke)(claims,evidence)
    assert [r['status'] for r in result]==['passed']*3
    assert invoke.call_count==1 and invoke.call_args.kwargs['use_reserve'] is True
    for e in evidence:assert e['quote'] in invoke.call_args.kwargs['prompt']
    assert (claims,evidence)==before


@pytest.mark.parametrize('defect',['missing','duplicate','malformed','borrowed_field'])
def test_one_bad_target_does_not_approve_it_or_discard_valid_siblings(defect):
    claims,evidence=inputs();raw=[response(c['claimId'],i) for i,c in enumerate(claims)]
    if defect=='missing':raw.pop(1)
    elif defect=='duplicate':raw.append(deepcopy(raw[1]))
    elif defect=='malformed':raw[1]['scopeAudit'].pop('supported')
    else:
        # A source-field reference from a sibling must fail its own target.
        raw[1].pop('reason');raw[1]['reasonParts']=[{'text':'A statement.', 'evidenceId':'E1','path':['quote']}]
    invoke=Mock(return_value={'content':json.dumps(raw)})
    result=checker(invoke)(claims,evidence)
    assert [r['status'] for r in result]==['passed','failed','passed']
    assert result[1]['executionState']=='received_invalid'
    assert invoke.call_count==1


def test_borrowed_scope_premise_fails_normal_own_source_gate():
    claims,evidence=inputs();raw=[response(c['claimId'],i) for i,c in enumerate(claims)]
    raw[1]['scopeAudit']['premises'][0]['evidenceId']='E1'
    result=checker(Mock(return_value={'content':json.dumps(raw)}))(claims,evidence)
    assert [r['status'] for r in result]==['passed','failed','passed']


@pytest.mark.parametrize('defect',['foreign','not_array','length'])
def test_unassignable_or_truncated_reply_keeps_entire_batch_unresolved(defect):
    claims,evidence=inputs();raw=[response(c['claimId'],i) for i,c in enumerate(claims)]
    if defect=='foreign':raw.append(response('foreign',0))
    elif defect=='not_array':raw={'unexpected':'value'}
    invoke=Mock(return_value={'content':json.dumps(raw),'finishReason':'length' if defect=='length' else 'stop'})
    result=checker(invoke)(claims,evidence)
    assert all(v['status']=='failed' and v['executionState']=='received_invalid' for v in result)
    assert invoke.call_count==1


def test_maximum_three_and_old_singleton_grouping_are_preserved():
    claims,evidence=inputs(4)
    def invoke(**kw):
        ids=list(dict.fromkeys(re.findall(r'"claimId"\s*:\s*"(c\d+)"',kw['prompt'])))
        return {'content':json.dumps([response(key,i) for i,key in enumerate(ids)])}
    active=Mock(side_effect=invoke);legacy=Mock(side_effect=invoke)
    assert all(v['status']=='passed' for v in checker(active)(claims,evidence))
    assert all(v['status']=='passed' for v in checker(legacy,False)(claims,evidence))
    assert active.call_count==2 and legacy.call_count==4


def test_four_initial_targets_keep_direct_review_and_validate_each_targets_own_sources():
    from services.deep_research.factual_review import DIRECT_REVIEW_OPTION

    claims, evidence = inputs(4)
    rows = [response(c['claimId'], i) for i, c in enumerate(claims)]
    rows[-1]['scopeAudit']['premises'][0]['evidenceId'] = 'E1'
    invoke = Mock(return_value={'content': json.dumps(rows)})
    semantic = checker(invoke)
    semantic._comparison_initial_review_targets = 4
    semantic._direct_comparison_review = True
    verdicts = semantic(claims, evidence)
    assert [v['status'] for v in verdicts] == ['passed', 'passed', 'passed', 'failed']
    invoke.assert_called_once()
    assert invoke.call_args.kwargs['extra_body'][DIRECT_REVIEW_OPTION] is True
    assert invoke.call_args.kwargs['extra_body']['max_tokens'] == 4000
    assert all(row['quote'] in invoke.call_args.kwargs['prompt'] for row in evidence)


def test_four_target_limit_still_splits_complete_input_over_the_capacity():
    claims, _ = inputs(4)
    def preview(batch):
        return {'inputBytes': 7000 * len(batch), 'maxInputBytes': 26000}

    assert groups(claims, preview, max_targets=4) == [claims[:3], claims[3:]]


def test_five_initial_targets_preserve_per_target_decoding_and_repair_limits():
    from test_deep_research_comparison_intent import record as comparison_record
    from services.deep_research.comparison_review_batches import initial_target_limit
    from services.deep_research.factual_review import DIRECT_REVIEW_OPTION

    record = {**comparison_record(), MARKER: 4, 'claimIsolationContractVersion': 1,
              'comparisonPlanningContractVersion': 6}
    limit = initial_target_limit(record)
    assert limit == 5
    assert initial_target_limit({**record, MARKER: 3}) == 4
    claims, evidence = inputs(limit)
    rows = [response(c['claimId'], i) for i, c in enumerate(claims)]
    rows[-1]['scopeAudit']['premises'][0]['evidenceId'] = 'E1'
    invoke = Mock(return_value={'content': json.dumps(rows)})
    semantic = checker(invoke)
    semantic._comparison_initial_review_targets = limit
    semantic._direct_comparison_review = True
    verdicts = semantic(claims, evidence)
    assert [row['status'] for row in verdicts] == ['passed'] * 4 + ['failed']
    assert semantic._comparison_target_limit('verify_repair') == 3
    invoke.assert_called_once()
    assert invoke.call_args.kwargs['extra_body'][DIRECT_REVIEW_OPTION] is True
    assert all(row['quote'] in invoke.call_args.kwargs['prompt'] for row in evidence)

def test_complete_oversized_quote_is_not_trimmed_or_sent():
    claims,evidence=inputs(1);evidence[0]['quote']='x'*40000
    evidence[0]['sourceContext']=evidence[0]['quote']
    invoke=Mock();result=checker(invoke)(claims,evidence)
    assert result[0]['status']=='failed' and result[0]['executionState']=='not_started'
    assert result[0]['reviewInputCapacity']['inputBytes']>24000
    invoke.assert_not_called()


def test_unknown_propagates_and_does_not_dispatch_next_group():
    claims,evidence=inputs(4);invoke=Mock(side_effect=UnknownCallError('unknown'))
    with pytest.raises(UnknownCallError):checker(invoke)(claims,evidence)
    assert invoke.call_count==1


def test_groups_preserve_all_targets_when_singleton_cannot_fit():
    claims,_=inputs(4);before=deepcopy(claims)
    result=groups(claims,lambda batch:{'inputBytes':100*len(batch),'maxInputBytes':50})
    assert result==[[c] for c in claims] and claims==before


@pytest.mark.parametrize('replacement',[None,True,pytest.param('1',id='1'),0,2,
                                       pytest.param(1,id='integer-1'),3])
def test_server_owned_marker_cannot_be_changed_or_injected(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'runs.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object(),comparison_cells_version=1,
                          comparison_review_batch_version=1)
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Compare methods',
            'deferStart':True,MARKER:replacement},start_async=False)
        assert type(r[MARKER]) is int and r[MARKER]==2
        if replacement==2 and type(replacement) is int:
            # Profile2 is now a valid server-selected value; a historical
            # profile1 must still reject the same attempted upgrade.
            old={**r,'runId':'old-profile1','taskId':'old-profile1','idempotencyKey':'old-profile1',MARKER:1}
            repo.create_run(old)
            with pytest.raises(ValueError,match='Immutable'):
                repo.update_run(old['runId'],lambda row:{**row,MARKER:replacement})
        else:
            with pytest.raises(ValueError,match='Immutable'):
                repo.update_run(r['runId'],lambda old:{**old,MARKER:replacement})
    finally:facade.shutdown()


def test_default_rollout_does_not_enable_batches_or_upgrade_old_missing_marker(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'runs.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object(),comparison_cells_version=1)
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Compare',
            'deferStart':True,MARKER:1},start_async=False)
        assert r[MARKER]==0 and not enabled(r)
        old={**r,'runId':'old','taskId':'old','idempotencyKey':'old'};old.pop(MARKER);repo.create_run(old)
        assert MARKER not in repo.update_run('old',lambda row:row)
        for value in (None,0):
            with pytest.raises(ValueError,match='Immutable'):
                repo.update_run('old',lambda row:{**row,MARKER:value})
    finally:facade.shutdown()


def test_actual_source_field_resolver_quarantines_only_borrowed_target():
    claims,evidence=inputs();raw=[response(c['claimId'],i) for i,c in enumerate(claims)]
    for i,row in enumerate(raw):
        row.pop('reason')
        row['reasonParts']=[{'text':'The cited observation supports this target.',
                             'evidenceId':f'E{i+1}','path':['quote']}]
    raw[1]['reasonParts'][0]['evidenceId']='E1'
    invoke=Mock(return_value={'content':json.dumps(raw)})
    c=checker(invoke);c._review_diagnostic_bindings=True;c._integrated_diagnostic_schema=True
    c._review_reason_parts=True;c._review_source_fields=True
    result=c(claims,evidence)
    assert [v['status'] for v in result]==['passed','failed','passed']
    assert result[1]['executionState']=='received_invalid'
    assert invoke.call_count==1


@pytest.mark.parametrize('scenario,repair',[
    pytest.param('success',False,id='success'),pytest.param('unknown',False,id='unknown'),
    pytest.param('success',True,id='repair-success'),pytest.param('unknown',True,id='repair-unknown')])
def test_real_sqlite_ledger_reuses_batch_identity_and_never_resends_unknown(tmp_path,scenario,repair):
    from llm.provider import LLMResult,LLMUsage,LLMProviderError
    from services.deep_research.contracts import DeepResearchError
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    from test_deep_research_shared_experiment_generation import context
    r,_,_=context();r[MARKER]=2 if repair else 1;r['comparisonPlanningContractVersion']=2
    r['state']['outputKind']='paper_comparison'
    repo=DeepResearchRepository(tmp_path/'ledger.sqlite3');repo.initialize();repo.create_run(r)
    repo.begin_execution('r');claims,evidence=inputs()
    client=Mock()
    if scenario=='unknown':
        client.invoke.side_effect=LLMProviderError('Timed out',provider='fixture',model='fixture',
                                                  failure_kind='read_timeout')
    else:
        client.invoke.return_value=LLMResult(content=json.dumps([response(c['claimId'],i)
            for i,c in enumerate(claims)]),provider='fixture',model='fixture',usage=LLMUsage(200,100,300))
    tracked=TrackedLLMInvoker(client,repo.reserve_call,repo.complete_call,run_record_fn=repo.require_run,
        verification_max_input_bytes=32000,call_history_fn=repo.list_calls)
    c=checker(tracked)
    c._comparison_repair_review_output=repair
    run=(lambda:c.check_revisions(claims,evidence,[])) if repair else (lambda:c(claims,evidence))
    if scenario=='success':
        first=run();snapshot=deepcopy(repo.list_calls('r'))
        assert run()==first
        assert all(v['status']=='passed' for v in first)
        assert snapshot[0]['status']=='succeeded' and snapshot[0]['settled']
    else:
        with pytest.raises(DeepResearchError):run()
        snapshot=deepcopy(repo.list_calls('r'))
        assert snapshot[0]['status']=='unknown' and not snapshot[0]['settled']
        with pytest.raises(DeepResearchError):run()
    assert len(snapshot)==1 and repo.list_calls('r')==snapshot
    assert client.invoke.call_count==1
    if repair:
        from services.deep_research.factual_review import REPAIR_OUTPUT_OPTION
        request=client.invoke.call_args.args[0]
        assert request.extra_body['max_tokens']==4000
        assert request.extra_body['thinking']=={'type':'disabled'}
        assert REPAIR_OUTPUT_OPTION not in request.extra_body


@pytest.mark.parametrize('value',[None,True,'1',0,2,3,4,5])
def test_batch_policy_requires_exact_server_marker_and_isolated_comparison_profile(value):
    from test_deep_research_shared_experiment_generation import context
    r,_,_=context();r['comparisonPlanningContractVersion']=2;r['state']['outputKind']='paper_comparison'
    r[MARKER]=1
    assert enabled(r)
    r[MARKER]=value
    assert enabled(r) is (type(value) is int and value in (2, 3, 4))
    r[MARKER]=1;r['claimIsolationContractVersion']=value
    assert not enabled(r)


def test_capacity_lower_bound_counts_bounded_batches_without_claiming_time_or_token_fit():
    from test_deep_research_shared_experiment_generation import context
    from services.deep_research.comparison_capacity import after_synthesis
    r,_,_=context();r['comparisonPlanningContractVersion']=2;r['state']['outputKind']='paper_comparison'
    r[MARKER]=1;r['stage']='synthesize';claims,_=inputs(4)
    r['state']['reportBody']={'claims':claims}
    result=after_synthesis(r)
    assert result['minimumReviewCalls']==2 and result['minimumWholeAnswerAuditCalls']==1
    assert not result['tokensAndTimeFitEstablished'] and not result['scientificApproval']
    r.pop(MARKER)
    assert after_synthesis(r)['minimumReviewCalls']==4


@pytest.mark.parametrize('version',[1,2])
def test_new_repair_output_cap_keeps_legacy_wire_and_same_reasoning_mode(version):
    from services.deep_research.factual_review import REPAIR_OUTPUT_OPTION
    from services.deep_research.runtime import research_model_options
    claims,evidence=inputs(1);invoke=Mock(return_value={'content':json.dumps([response('c0',0)])})
    c=checker(invoke);c._comparison_repair_review_output=version==2
    assert c.check_revisions(claims,evidence,[])[0]['status']=='passed'
    kw=invoke.call_args.kwargs;options=research_model_options(kw['node'],kw['extra_body'])
    assert options['thinking']=={'type':'disabled'} and options['reasoning_effort']=='none'
    assert options['max_tokens']==(4000 if version==2 else 8192)
    assert (REPAIR_OUTPUT_OPTION in kw['extra_body']) is (version==2)
    assert REPAIR_OUTPUT_OPTION not in options


@pytest.mark.parametrize('version',[None,0,1])
def test_old_runs_cannot_inject_new_repair_output_before_reservation(version):
    from services.deep_research.factual_review import REPAIR_OUTPUT_OPTION
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.contracts import DeepResearchError
    from test_deep_research_shared_experiment_generation import context
    r,_,_=context();r[MARKER]=version;r['comparisonPlanningContractVersion']=2;r['state']['outputKind']='paper_comparison'
    client=Mock();reserve=Mock()
    invoke=TrackedLLMInvoker(client,reserve,Mock(),run_record_fn=lambda _:r)
    with pytest.raises(DeepResearchError,match='版本不匹配'):
        invoke('r','verify_repair','unchanged sources',{'max_tokens':4000,REPAIR_OUTPUT_OPTION:True},use_reserve=True)
    reserve.assert_not_called();client.invoke.assert_not_called()


@pytest.mark.parametrize('repair',[False,True])
def test_current_profile_shares_only_exact_source_values_and_preserves_all_restored_fields(monkeypatch,repair):
    from services.deep_research import shared_strings
    from services.deep_research.nested_tables import unpack as untables
    claims,evidence=inputs();captured=[]
    for e in evidence:e['conditions']={'setup':'The same exact documented setup. '*60}
    before=deepcopy((claims,evidence));original=shared_strings.input_text
    def encode(value):
        rendered=original(value);wire=json.JSONDecoder().raw_decode(rendered)[0]
        restored=untables(shared_strings.unpack(wire)) if set(wire)=={'strings','value'} else wire
        assert restored==value
        captured.append((deepcopy(value),rendered));return rendered
    monkeypatch.setattr(shared_strings,'input_text',encode)
    invoke=Mock(return_value={'content':json.dumps([response(c['claimId'],i) for i,c in enumerate(claims)])})
    current=checker(invoke);current._comparison_repair_review_output=True
    result=current.check_revisions(claims,evidence,[]) if repair else current(claims,evidence)
    assert captured and all(v['status']=='passed' for v in result)
    view,rendered=captured[-1]
    assert len(view['evidence'])==3 and len(view['sources'])==3
    assert len(rendered.encode())<len(json.dumps(view,ensure_ascii=False,separators=(',',':')).encode())
    assert (claims,evidence)==before
    captured.clear();old=checker(invoke);old._comparison_repair_review_output=False
    old.check_revisions(claims,evidence,[]) if repair else old(claims,evidence)
    assert not captured
