from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.experiment_execution_guidance import enabled, data_declarations, PLANNING, DRAFTING, REVIEW
from services.deep_research.experiment_planning import planning_prompt,prepare_plan
from services.deep_research.experiment_review_envelope import build
from services.deep_research.contracts import DeepResearchError
from services.deep_research.graph import make_synthesize_node
from test_deep_research_review_envelope import args
from test_deep_research_shared_experiment_repair import json_after
from test_deep_research_generation_envelope import current
from test_deep_research_experiment_planning import Store,response
from test_deep_research_lean_planning import lean_basis
from test_deep_research_experiment_representation import wrapped_claims


def test_exact_declared_data_values_including_invalid_values_are_preserved_without_validation():
    c=json.loads(args('data')['claims_text'])[0]
    c['executionSpec'].update(seeds=[0],split={'mode':'every_nth','stride':5,'offset':0,'order':'camera_id'})
    before=deepcopy(c);index=data_declarations([c]);row=index[0]
    assert row['claimId']==c['claimId'] and not row['absentFields']
    assert next(v for v in row['declaredFields'] if v['path']==['executionSpec','seeds'])['value']==[0]
    row['declaredFields'][0]['value']['mode']='changed'
    assert c==before
    c['executionSpec']['seeds']=[]
    assert next(v for v in data_declarations([c])[0]['declaredFields'] if v['path'][-1]=='seeds')['value']==[]
    del c['executionSpec']['seeds']
    assert data_declarations([c])[0]['absentFields']==[['executionSpec','seeds']]


@pytest.mark.parametrize('change',['duplicate','fact','wrong_contract','non_spec','bad_id','wrong_role'])
def test_ambiguous_or_foreign_declarations_never_get_assigned_to_a_target(change):
    c=json.loads(args('data')['claims_text'])[0];claims=[c]
    if change=='duplicate':claims.append(deepcopy(c))
    elif change=='fact':c['kind']='reported'
    elif change=='wrong_contract':c['designContractVersion']=True
    elif change=='non_spec':c['executionSpec']=None
    elif change=='bad_id':c['claimId']=[]
    else:c['designRole']='steps'
    assert data_declarations(claims)==[]


def test_review_keeps_old_request_and_complete_values_but_adds_exact_presence_pointers():
    kw=args('data');before=deepcopy(kw)
    old=build(**kw,version=3);new=build(**kw,version=4)
    assert new.startswith(old+'\n\n'+REVIEW)
    index=json_after(new,'Exact data declarations (not evidence or approval):\n')
    assert index==data_declarations([*json.loads(kw['claims_text']),*kw['context']])
    assert kw==before and 'without an executionSpec grammar' in new


@pytest.mark.parametrize('version',[None,True,False,0,'1',3])
def test_other_version_values_do_not_change_planning_messages(version):
    kw=dict(question='Exact task α',obligations=[],sources={},evidence=[],tables={},metric_domains=['quality'])
    assert planning_prompt(**kw,execution_guidance_version=version)==planning_prompt(**kw)
    assert not enabled({'experimentExecutionGuidanceContractVersion':version})
    assert planning_prompt(**kw,execution_guidance_version=1)==planning_prompt(**kw)+'\n'+PLANNING


def test_graph_uses_execution_decisions_in_both_actual_requests_without_inventing_config_values():
    record=current();record['experimentExecutionGuidanceContractVersion']=1
    store=Store(record);invoke=Mock(side_effect=[response(lean_basis()),response({'sections':[],'claims':wrapped_claims()})])
    result=make_synthesize_node(invoke,store.update)({'run_id':'r'})
    assert not result.get('error_code') and invoke.call_count==2
    saved=store.value['state']['experimentPlanning']
    assert PLANNING in saved['request']['prompt'] and DRAFTING in saved['draftRequest']['prompt']
    assert store.value['state']['reportBody']['claims']  # Existing parsing, no seed/state injection.


@pytest.mark.parametrize('replacement',[None,True,'1',0,1,3])
def test_execution_guidance_is_server_owned_and_strictly_immutable(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'runs.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        row,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Experiment',
            'deferStart':True,'experimentExecutionGuidanceContractVersion':replacement},start_async=False)
        assert row['experimentExecutionGuidanceContractVersion']==2
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(row['runId'],lambda r:{**r,'experimentExecutionGuidanceContractVersion':replacement})
    finally:facade.shutdown()


def test_unknown_planning_request_cannot_switch_to_new_decision_instructions_or_resend():
    store=Store(current());base='Frozen original evidence';invoke=Mock(side_effect=OSError('unknown'))
    with pytest.raises(OSError):
        prepare_plan(store.value,prompt=base,aliases={'E1':'source'},invoke=invoke,parse=json.loads,checkpoint=store.checkpoint)
    saved=deepcopy(store.value['state']['experimentPlanning']);invoke.reset_mock()
    with pytest.raises(DeepResearchError):
        prepare_plan(store.value,prompt=base+'\n'+PLANNING,aliases={'E1':'source'},invoke=invoke,parse=json.loads,checkpoint=store.checkpoint)
    invoke.assert_not_called();assert store.value['state']['experimentPlanning']==saved
