"""Parameter spelling may remove an index, never a measured or assigned value."""
from copy import deepcopy
import json

import pytest

from services.deep_research.review_diagnostics import bind
from test_deep_research_factual_decision import checker, evidence, response, target


def inputs(reason='The supplied parameter β2 is discussed.', quote='Parameter β2 is supplied.'):
    claim={**target(),'text':'A bounded observation.'}
    ev=evidence();ev[0]['quote']=quote
    verdict={'claimId':'c','status':'failed','reason':reason,'diagnosticFacts':[]}
    return verdict,claim,ev


@pytest.mark.parametrize('name',['β2','β1','α12','β_2'])
def test_visible_parameter_identity_is_not_an_added_measurement(name):
    verdict,claim,ev=inputs(f'The supplied parameter {name} is discussed.',f'Parameter {name} is supplied.')
    before=deepcopy((verdict,claim,ev))
    result=bind(verdict,claim,ev,source_parameter_ids=True)
    assert result['reviewDiagnosticAudit']['errors']==[]
    assert result['reviewDiagnosticAudit']['newNumberCount']==0
    assert result['reviewDiagnosticAudit']['sourceParameterIdentityContractVersion']==1
    assert result['status']=='failed' and result['reason']==verdict['reason']
    assert (verdict,claim,ev)==before


def test_unmarked_legacy_binding_retains_original_result():
    verdict,claim,ev=inputs()
    baseline=bind(verdict,claim,ev)
    assert bind(verdict,claim,ev,source_parameter_ids=False)==baseline
    assert baseline['reviewDiagnosticAudit']['errors']==['new_diagnostic_numbers_not_bound']
    assert 'sourceParameterIdentityContractVersion' not in baseline['reviewDiagnosticAudit']


@pytest.mark.parametrize('reason',[
    'β2=0.999 is the default.', 'β=2 is supplied.', 'The result is 2.',
    '算法第3行显示该结果。', 't=1 is sufficient.', 'β3 is supplied.',
    'β2x is the value.', 'β2% is the value.', 'β2× is the value.',
    'β2倍为该值。', 'β2ms is the value.',
])
def test_real_numbers_unknown_parameters_and_ambiguous_units_remain_unbound(reason):
    verdict,claim,ev=inputs(reason,'Parameter β2 has coefficient 0.001.')
    result=bind(verdict,claim,ev,source_parameter_ids=True)
    assert result['executionState']=='received_invalid'
    assert 'new_diagnostic_numbers_not_bound' in result['reviewDiagnosticAudit']['errors']


@pytest.mark.parametrize('field',['title','foreign','hidden','omitted'])
def test_parameter_identity_requires_own_visible_source_field(field):
    verdict,claim,ev=inputs(quote='An observation.')
    if field=='title':ev[0]['sourceTitle']='Parameter β2'
    elif field=='foreign':ev.append({'evidenceId':'other','quote':'Parameter β2'})
    elif field=='hidden':ev[0]['fullText']='Parameter β2'
    else:ev[0].update(sourceContext={},contextOmitted=True)
    result=bind(verdict,claim,ev,source_parameter_ids=True)
    assert result['reviewDiagnosticAudit']['errors']==['new_diagnostic_numbers_not_bound']


@pytest.mark.parametrize('context',['Parameter β2',{'before':'Parameter β2'},{'after':'Parameter β2'}])
def test_actually_supplied_source_context_can_define_parameter_identity(context):
    verdict,claim,ev=inputs(quote='An observation.');ev[0]['sourceContext']=context
    assert bind(verdict,claim,ev,source_parameter_ids=True)['reviewDiagnosticAudit']['errors']==[]


@pytest.mark.parametrize('mutation',['statement','excerpt','path','foreign'])
def test_parameter_identity_does_not_relax_exact_source_binding(mutation):
    verdict,claim,ev=inputs()
    fact={'statement':verdict['reason'],'evidenceId':'own','path':['quote'],'excerpt':ev[0]['quote']}
    if mutation=='statement':fact['statement']='A different statement.'
    elif mutation=='excerpt':fact['excerpt']='Parameter β2 is proven.'
    elif mutation=='path':fact['path']=['sourceTitle']
    else:fact['evidenceId']='other'
    verdict['diagnosticFacts']=[fact]
    assert bind(verdict,claim,ev,source_parameter_ids=True)['reviewDiagnosticAudit']['errors']


@pytest.mark.parametrize('value',[None,0,1,'1'])
def test_direct_binding_policy_is_strict_boolean(value):
    with pytest.raises(ValueError):bind(*inputs(),source_parameter_ids=value)


@pytest.mark.parametrize('supported',[True,False])
def test_checker_uses_visible_fields_without_changing_request_or_model_decision(supported):
    _,claim,ev=inputs();raw={**response(supported),'reason':'The supplied parameter β2 is discussed.','diagnosticFacts':[]}
    calls=[]
    def invoke(**kwargs):calls.append(kwargs);return {'content':json.dumps([raw])}
    old=checker(invoke,review_diagnostic_bindings=True)([claim],ev)[0];old_request=calls.pop()
    result=checker(invoke,review_diagnostic_bindings=True,diagnostic_parameter_ids=lambda:True)([claim],ev)[0]
    assert calls==[old_request]
    assert old['executionState']=='received_invalid'
    assert result['reviewDiagnosticAudit']['errors']==[]
    assert result['status']==('passed' if supported else 'failed')


def test_version_flag_is_server_owned_immutable_and_absent_from_legacy_runs(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    key='reviewParameterIdentityContractVersion'
    try:
        row,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain','deferStart':True,key:False},start_async=False)
        assert type(row[key]) is int and row[key]==1
        assert facade._make_semantic_checker(row['runId'])._diagnostic_parameter_ids() is True
        old=deepcopy(row);old.update(runId='old',idempotencyKey='old');old.pop(key);repo.create_run(old)
        assert facade._make_semantic_checker('old')._diagnostic_parameter_ids() is False
        for run_id in (row['runId'],'old'):
            with pytest.raises(ValueError,match='Immutable'):
                repo.update_run(run_id,lambda r:{**r,key:2})
    finally:facade.shutdown()


def test_bound_parameter_label_does_not_hide_an_unbound_algorithm_line():
    verdict,claim,ev=inputs('算法第3行的 β2 使用系数 0.001。','β2 使用系数 0.001。')
    verdict['diagnosticFacts']=[{'statement':verdict['reason'],'evidenceId':'own',
        'path':['quote'],'excerpt':ev[0]['quote']}]
    result=bind(verdict,claim,ev,source_parameter_ids=True)
    assert result['reviewDiagnosticAudit']['newNumberCount']==2
    assert result['reviewDiagnosticAudit']['unboundNewNumberCount']==1
    assert result['executionState']=='received_invalid'


def test_assigned_coefficient_still_requires_exact_bound_source():
    verdict,claim,ev=inputs('The coefficient β2=0.001 is supplied.','The coefficient β2=0.001 is supplied.')
    verdict['diagnosticFacts']=[{'statement':verdict['reason'],'evidenceId':'own',
        'path':['quote'],'excerpt':ev[0]['quote']}]
    result=bind(verdict,claim,ev,source_parameter_ids=True)
    assert result['reviewDiagnosticAudit']['newNumberCount']==1
    assert result['reviewDiagnosticAudit']['errors']==[]


@pytest.mark.parametrize('policy',[False,True])
def test_partitioned_scope_operator_uses_same_parameter_policy(policy):
    from test_deep_research_partitioned_scope_review import inputs as scope_inputs,checker_for
    claim,expression,record,ev=scope_inputs(settings=False)
    ev[0]['quote']+=' The parameter β2 is supplied.'
    c,calls=checker_for(claim,expression,record,ev)
    original=c._invoke
    def invoke(**kwargs):
        result=original(**kwargs);rows=json.loads(result['content'])
        for row in rows:row.update(reason='The parameter β2 does not establish every setting.',diagnosticFacts=[])
        return {**result,'content':json.dumps(rows)}
    c._invoke=invoke;c._review_diagnostic_bindings=True;c._diagnostic_parameter_ids=policy
    result=c([claim],ev)[0]
    assert len(calls)==1
    assert result['status']==('passed' if policy else 'failed')


def test_fitted_prompt_omitted_context_cannot_supply_parameter_identity():
    from services.deep_research.prompt_budget import fit_evidence_prompt
    verdict,claim,ev=inputs(quote='An observation.')
    ev[0]['sourceContext']='Hidden parameter β2. '*100
    render=lambda rows:json.dumps(rows,ensure_ascii=False)
    prompt,visible=fit_evidence_prompt(ev,render,max_bytes=250)
    assert 'β2' not in prompt and visible[0]['contextOmitted'] is True
    result=bind(verdict,claim,visible,source_parameter_ids=True)
    assert result['reviewDiagnosticAudit']['errors']==['new_diagnostic_numbers_not_bound']
