from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.configuration_consistency import facts,enabled,GENERATION,REVIEW
from services.deep_research.tools import BudgetedSemanticChecker
from test_deep_research_shared_experiment_repair import inputs


def choices():
    claims=inputs()[0]['claims']
    data=next(c for c in claims if c['designRole']=='data')
    data['protocolContractVersion']=2
    data['executionSpec']['split']={'mode':'every_nth','order':'camera_index','stride':2,'offset':0}
    budget=next(c for c in claims if c['designRole']=='budget')
    budget['executionSpec']={'baseline':{'mode':'train','unit':'optimizer_steps','maxBudget':1000,'stoppingRule':'fixed cap'},
        'recovery':{'mode':'unmatched','unit':'optimizer_steps','groups':{'0':0,'1':2000},'note':'Whole-stage cost, not isolated parameter effect.'}}
    return data,budget


def test_derived_split_and_caps_use_only_explicit_fields_and_preserve_original_prose():
    data,budget=choices();data['text']='Contradictory prose: even cameras train; choose 999 frames.'
    before=deepcopy([data,budget]);rows=facts([data,budget])
    assert rows[0]['splitMeaning']=='按camera_index排列，样本从0开始编号，编号除以2的余数为0时划入评估集，其余为训练集'
    assert rows[1]['perGroupUpperCaps']=={'0':{'sum':[1000,0],'upperCap':1000},'1':{'sum':[1000,2000],'upperCap':3000}}
    assert [data,budget]==before and '999' not in json.dumps(rows)
    assert 'every' not in json.dumps(rows)  # No inferred frame count or multiplier.
    assert not any('verification' in r for r in rows)


@pytest.mark.parametrize('change,reason',[('existing','existing_asset_cost_not_declared'),('units','different_units')])
def test_no_implicit_zero_asset_cost_or_adding_incompatible_units(change,reason):
    _,budget=choices()
    if change=='existing':budget['executionSpec']['baseline']={'mode':'existing','selectionRule':'Unverified proposed locator'}
    else:budget['executionSpec']['baseline']['unit']='wall_seconds'
    row=facts([budget])[0]
    assert row['totalNotComputed']==reason and 'perGroupUpperCaps' not in row


@pytest.mark.parametrize('change',['unequal_matched','bool','negative','infinite','unit_list','missing','extra','expression'])
def test_invalid_or_executable_looking_values_never_become_valid_caps(change):
    _,budget=choices();spec=budget['executionSpec']
    if change=='unequal_matched':spec['recovery'].pop('note');spec['recovery']['mode']='matched'
    elif change=='bool':spec['baseline']['maxBudget']=True
    elif change=='negative':spec['recovery']['groups']['1']=-1
    elif change=='infinite':spec['baseline'].update(unit='wall_seconds',maxBudget=float('inf'))
    elif change=='unit_list':spec['recovery']['unit']=[]
    elif change=='missing':del spec['recovery']
    elif change=='extra':spec['total']=3000
    else:spec['baseline']['maxBudget']="__import__('os').system('not executed')"
    row=facts([budget])[0]
    assert row['schemaErrors'] and 'perGroupUpperCaps' not in row
    json.dumps(row,allow_nan=False)


@pytest.mark.parametrize('kind',['float_sum','mixed_bigint'])
def test_finite_inputs_with_unrepresentable_sum_are_not_serialized_as_infinity(kind):
    _,budget=choices();spec=budget['executionSpec']
    spec['baseline'].update(unit='wall_seconds',maxBudget=1e308)
    spec['recovery'].update(unit='wall_seconds',groups={'0':0,'1':1e308 if kind=='float_sum' else 10**400})
    row=facts([budget])[0]
    assert row['perGroupUpperCaps']['1']=={'notComputed':'unsupported_sum'}
    json.dumps(row,allow_nan=False)


@pytest.mark.parametrize('field,value',[('designContractVersion',True),('budgetContractVersion','1'),('kind','reported')])
def test_unversioned_or_factual_choices_do_not_get_proposal_calculations(field,value):
    _,budget=choices();budget[field]=value
    assert facts([budget])==[]


def test_ambiguous_claim_ids_are_not_resolved_by_order_or_choosing_a_preferred_value():
    _,budget=choices();other=deepcopy(budget);other['executionSpec']['baseline']['maxBudget']=99
    assert facts([budget,other])==facts([other,budget])==[]


def invoke_for(version):
    data,budget=choices();sent=[]
    def invoke(**request):
        sent.append(request)
        targets=json.JSONDecoder().raw_decode(request['prompt'].split('Claims:',1)[1].lstrip())[0]
        return {'content':json.dumps([{'claimId':c['claimId'],'status':'failed','reason':'Actual missing phase/prose mismatch.'} for c in targets])}
    checker=BudgetedSemanticChecker(invoke,'offline',configuration_consistency=version,prospective_review=2,experiment_intent_review=3)
    result=checker.check_revisions([budget],inputs()[2],[data])
    return sent,result


def test_reviewer_receives_exact_derived_fields_and_all_original_claims_without_promoting_a_verdict():
    old,old_result=invoke_for(0);new,new_result=invoke_for(lambda:1)
    assert len(old)==len(new)==1 and new_result==old_result and new_result[0]['status']=='failed'
    head,tail=new[0]['prompt'].split('\n'+REVIEW+'\nDerived configuration meanings (not evidence):\n')
    rows=json.loads(tail)
    assert head==old[0]['prompt'] and rows==facts(list(reversed(choices())))
    assert new[0]['extra_body']==old[0]['extra_body'] and len(new[0]['prompt'].encode())<=24000


@pytest.mark.parametrize('version',[None,True,False,'1',0,3])
def test_missing_wrong_type_and_other_versions_keep_legacy_request_exact(version):
    old,_=invoke_for(0);new,_=invoke_for(version)
    assert old==new and not enabled(version)


@pytest.mark.parametrize('replacement',[None,True,'1',0,1])
def test_consistency_contract_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'runs.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        value,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Propose an experiment',
            'configurationConsistencyContractVersion':replacement,'deferStart':True},start_async=False)
        assert value['configurationConsistencyContractVersion']==2
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(value['runId'],lambda r:{**r,'configurationConsistencyContractVersion':replacement})
    finally:facade.shutdown()


@pytest.mark.parametrize('version',[0,1])
def test_generation_emphasizes_one_rendered_setting_source_only_for_new_contract(version):
    from services.deep_research.graph import make_synthesize_node
    from test_deep_research_lean_planning import record,lean_basis
    from test_deep_research_experiment_representation import wrapped_claims
    from test_deep_research_experiment_planning import Store,response
    current=record();current['configurationConsistencyContractVersion']=version;store=Store(current)
    body={'sections':[],'claims':wrapped_claims()};raw=deepcopy(body)
    invoke=Mock(side_effect=[response(lean_basis()),response(body)])
    result=make_synthesize_node(invoke,store.update)({'run_id':'r'})
    assert 'error_code' not in result and body==raw
    assert (GENERATION in invoke.call_args.args[2]) is (version==1)
    assert store.value['state']['reportBody']['claims']
