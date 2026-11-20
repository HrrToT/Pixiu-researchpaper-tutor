"""A bounded revision window never relaxes scope, output or run budgets."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.workflow_revision_input import enabled,input_limit,NODE
from services.deep_research.workflow_metadata_repair import prepare,prompt_for
from services.deep_research.workflow_metadata_symbols import decode,field_feedback
from services.deep_research.workflow_metadata_envelope import GUIDANCE
from services.deep_research.planning_transport import overhead_bytes
from services.deep_research.contracts import digest,DeepResearchError,BudgetExhaustedError
from services.deep_research.tools import TrackedLLMInvoker
from test_deep_research_metadata_envelope import record as previous,wire


def record():return {**previous(),'workflowRevisionInputContractVersion':1}


@pytest.mark.parametrize('marker',[None,True,False,0,2,'1'])
def test_version_is_strict_and_legacy_keeps_32kb(marker):
    r={**record(),'workflowRevisionInputContractVersion':marker}
    assert not enabled(r) and input_limit(r)==32000


@pytest.mark.parametrize('key',['workflowMetadataEnvelopeContractVersion','workflowMetadataOutputContractVersion',
 'workflowMetadataRepairContractVersion','executionWorkflowContractVersion','structuredOutputContractVersion'])
def test_partial_profiles_cannot_use_revision_window(key):
    assert not enabled({**record(),key:0})


def failed():
    w=wire();v=decode(w);response={'content':json.dumps(w),'finishReason':'stop'}
    return w,{'status':'invalid_response','request':{'prompt':'original'},'response':response,
      'responseDigest':digest(response),'value':v,'valueDigest':digest(v),'errors':['timeline.phase.action']}


class StopBeforeProvider(Exception):pass


def sized_source(r,w,size):
    aliases={k:k for k in w['sourceRefs']};feedback=field_feedback(w,aliases)
    feedback={**feedback,'codes':['timeline.phase.action']}
    base={'question':''}
    n=len((GUIDANCE+prompt_for(json.dumps(base),w,feedback,version=34)).encode())+overhead_bytes(r,NODE)
    assert n<size
    base['question']='q'*(size-n)
    assert len((GUIDANCE+prompt_for(json.dumps(base),w,feedback,version=34)).encode())+overhead_bytes(r,NODE)==size
    return json.dumps(base),aliases


@pytest.mark.parametrize('size,allowed',[(32001,True),(38117,True),(40000,True),(40001,False)])
def test_actual_revision_admission_keeps_complete_source_and_boundary(size,allowed):
    r=record();w,u=failed();source,aliases=sized_source(r,w,size);saved=[]
    invoke=Mock(side_effect=StopBeforeProvider())
    before=deepcopy(u)
    with pytest.raises(StopBeforeProvider if allowed else DeepResearchError):
        prepare(r,source_data=source,failed=u,aliases=aliases,existing=None,invoke=invoke,checkpoint=saved.append)
    assert u==before and invoke.call_count==int(allowed)
    assert saved[-1]['scientificApproval'] is False
    assert saved[-1]['status']==('pending' if allowed else 'not_started_capacity')
    if not allowed:assert saved[-1]['inputBytes']==40001 and saved[-1]['maxInputBytes']==40000


def test_legacy_capacity_failure_is_not_reinterpreted_or_resent():
    r=previous();w,u=failed();source,aliases=sized_source(r,w,38117);saved=[];invoke=Mock()
    with pytest.raises(DeepResearchError,match='超限'):
        prepare(r,source_data=source,failed=u,aliases=aliases,existing=None,invoke=invoke,checkpoint=saved.append)
    assert saved[-1]['status']=='not_started_capacity'
    # Even an invalid in-memory mutation cannot repurpose the frozen failure.
    r['workflowRevisionInputContractVersion']=1
    with pytest.raises(DeepResearchError,match='不一致'):
        prepare(r,source_data=source,failed=u,aliases=aliases,existing=saved[-1],invoke=invoke,checkpoint=saved.append)
    invoke.assert_not_called()


@pytest.mark.parametrize('configured',[24000,32000,40000])
def test_invoker_honors_server_cap_and_leaves_other_nodes_unchanged(configured):
    reserve=Mock(side_effect=BudgetExhaustedError('tokens',100001,100000));client=Mock()
    call=TrackedLLMInvoker(client,reserve,Mock(),run_record_fn=lambda _:record(),
      experiment_max_input_bytes=32000,workflow_revision_max_input_bytes=configured)
    assert call.prompt_byte_limit('r',NODE)==configured
    assert call.prompt_byte_limit('r','plan_workflow_meta')==32000
    assert call.prompt_byte_limit('r','plan_workflow_init')==32000
    n=configured-overhead_bytes(record(),NODE)
    with pytest.raises(BudgetExhaustedError):call('r',NODE,'x'*n,{'max_tokens':6144})
    assert reserve.call_args.kwargs['budget_delta']['tokens']==configured+1024+6144
    with pytest.raises(ValueError,match='Prompt too large'):call('r',NODE,'x'*(n+1),{'max_tokens':6144})
    assert reserve.call_count==1
    client.invoke.assert_not_called()


@pytest.mark.parametrize('cap',[True,0,40001,'40000'])
def test_bad_server_caps_rejected(cap):
    with pytest.raises(ValueError,match='workflow revision'):
        TrackedLLMInvoker(Mock(),Mock(),Mock(),workflow_revision_max_input_bytes=cap)


def test_legacy_ignores_new_configured_window():
    call=TrackedLLMInvoker(Mock(),Mock(),Mock(),run_record_fn=lambda _:previous(),
       experiment_max_input_bytes=32000,workflow_revision_max_input_bytes=40000)
    assert call.prompt_byte_limit('r',NODE)==32000


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_marker_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Design','deferStart':True,
          'workflowRevisionInputContractVersion':replacement},start_async=False)
        assert enabled(r)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda x:{**x,'workflowRevisionInputContractVersion':replacement})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');old.pop('workflowRevisionInputContractVersion');repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run('old',lambda x:{**x,'workflowRevisionInputContractVersion':1})
    finally:facade.shutdown()
