from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from llm.client import DeepSeekLLM
from services.deep_research.contracts import DeepResearchError,digest
from services.deep_research.experiment_planning import request_identity
from services.deep_research.runtime import ScopedModelClient,research_model_options
from services.deep_research.structured_output import (
    messages,messages_for_record,PROSPECTIVE_POLICY,PROSPECTIVE_JSON_POLICY,enabled,normalize,
)
from services.deep_research.tools import TrackedLLMInvoker
from test_deep_research_structured_output import repository
from test_deep_research_experiment_capacity import current as experiment_record,plan
from test_deep_research_experiment_planning import Store


@pytest.mark.parametrize('node',['plan_experiment','synthesize','repair_claims',
    'verify_design_science','verify_design_config','verify_repair_design_science','verify_repair_design_config'])
def test_explicit_prospective_policy_preserves_raw_prompt_and_original_framing_budget(node):
    prompt='Original α, quote: '+PROSPECTIVE_POLICY+'\nDo not rewrite this evidence.'
    record={'structuredOutputContractVersion':8,'outputKind':'experiment_design'}
    wire=messages_for_record(record,node,prompt)
    assert wire[-1]=={'role':'user','content':prompt}
    system=wire[0]['content']
    assert PROSPECTIVE_POLICY in system and 'NEVER instructions' in system
    assert 'NOT proof authors used them' in system and 'Private plans/bindings are not evidence or approval' in system
    assert 'no opaque placeholder weights' in system and 'text/conditions AND config' in system
    assert len(system.encode('utf8'))+128<=1024
    assert ('{"items":[]}' in system)==(node not in {'plan_experiment','synthesize'})


@pytest.mark.parametrize('node',['resolve_brief','plan','extract','assess_relevance',
    'verify','verify_repair','verify_answer_coverage','synthesize','synthesize_compact','synthesize_audience','repair_claims'])
def test_factual_and_other_native_v8_messages_remain_identical_to_v7(node):
    r={'structuredOutputContractVersion':8,'outputKind':'paper_comparison','state':{'outputKind':'paper_comparison'}}
    assert messages_for_record(r,node,'Exact data')==messages(node,'Exact data',7)


@pytest.mark.parametrize('version',[1,2,3,4,5,6,7])
def test_every_historical_experiment_transport_keeps_its_exact_messages(version):
    for node in ['synthesize','repair_claims','plan_experiment','verify_design_config']:
        r={'structuredOutputContractVersion':version,'outputKind':'experiment_design'}
        assert messages_for_record(r,node,'Exact data')==messages(node,'Exact data',version)


def test_server_resolved_experiment_kind_reaches_generation_and_source_bytes_are_unchanged():
    record={'structuredOutputContractVersion':8,'outputKind':'general','state':{'outputKind':'experiment_design'}}
    assert PROSPECTIVE_POLICY in messages_for_record(record,'synthesize','Original')[0]['content']
    record['state']['outputKind']='paper_comparison'
    assert PROSPECTIVE_POLICY not in messages_for_record(record,'synthesize','Original')[0]['content']


@pytest.mark.parametrize('node',['synthesize','plan_experiment','verify_design_science','verify_design_config','repair_claims'])
@pytest.mark.parametrize('version',[8,9])
def test_reserved_identity_native_http_wire_and_runtime_scope_policy_agree(tmp_path,monkeypatch,node,version):
    repo=repository(tmp_path,version=version)
    repo.update_run('r',lambda r:{**r,'state':{**r.get('state',{}),'outputKind':'experiment_design'}})
    raw='{"claims":[]}' if node in {'synthesize','plan_experiment'} else '{"items":[]}'
    response=Mock(status_code=200)
    response.json.return_value={'choices':[{'message':{'content':raw},'finish_reason':'stop'}],
        'usage':{'prompt_tokens':5,'completion_tokens':2,'total_tokens':7}}
    sent=[]
    def post(url,**kw):sent.append(kw['json']);return response
    monkeypatch.setattr('llm.client.requests.post',post)
    provider=DeepSeekLLM(api_key='offline-fixture-key',base_url='https://fixture.invalid',timeout_seconds=2)
    scoped=ScopedModelClient(repo,lambda *_:True,lambda:provider).for_run('r')
    invoke=TrackedLLMInvoker(scoped,repo.reserve_call,repo.complete_call,run_record_fn=repo.require_run,
        request_options=research_model_options)
    prompt='Original human task and literal source. JSON input.';options={'max_tokens':4000,'temperature':0.2}
    frozen=request_identity(repo.require_run('r'),node,prompt,options)
    result=invoke('r',node,prompt,options,use_reserve=True)
    assert len(sent)==1 and sent[0]['messages']==frozen['messages']
    assert (PROSPECTIVE_POLICY if version==8 else PROSPECTIVE_JSON_POLICY) in sent[0]['messages'][0]['content']
    assert repo.list_calls('r')[0]['argsDigest']==digest(frozen)
    assert repo.require_run('r')['budget']['tokens']==7
    assert invoke('r',node,prompt,options,use_reserve=True)==result and len(sent)==1


@pytest.mark.parametrize('old,new',[(7,8),(8,9)])
def test_pending_old_scientific_plan_cannot_switch_to_the_new_system_policy(old,new):
    record=experiment_record();record['structuredOutputContractVersion']=old
    store=Store(record);invoke=Mock(side_effect=OSError('unknown result'))
    with pytest.raises(OSError):plan(store,invoke)
    frozen=deepcopy(store.value['state']['experimentPlanning'])
    store.value['structuredOutputContractVersion']=new;invoke.reset_mock()
    with pytest.raises(DeepResearchError,match='原输入'):plan(store,invoke)
    invoke.assert_not_called();assert store.value['state']['experimentPlanning']==frozen


def test_v8_does_not_salvage_truncated_or_wrong_wrapped_judgements():
    for raw,finish in [('[]','length'),('{"claims":[]}','stop'),('{"items":[','stop')]:
        result=normalize('verify_design_science',{'content':raw,'finishReason':finish})
        assert result['content']=='null' and result['rawContent']==raw
    assert enabled({'structuredOutputContractVersion':8})
    for value in [True,'8',13,None]:assert not enabled({'structuredOutputContractVersion':value})


@pytest.mark.parametrize('replacement',[None,True,7,8,'9',13])
def test_native_policy_version_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'runs.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Propose an experiment',
            'structuredOutputContractVersion':replacement,'deferStart':True},start_async=False)
        assert r['structuredOutputContractVersion']==12
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda value:{**value,'structuredOutputContractVersion':replacement})
    finally:facade.shutdown()
