"""Four-arm transport fixtures prove engineering bounds, never scientific quality."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.execution_workflow_blueprint import prepare,prompt_for,packed
from services.deep_research.workflow_metadata_envelope import enabled,limits,over_capacity,GUIDANCE
from services.deep_research.workflow_metadata_symbols import decode,field_feedback
from test_deep_research_symbolic_metadata_allowance import record as output_record


def record():
    return {**output_record(),'workflowMetadataEnvelopeContractVersion':1}


def wire(*,unique_fixture_names=False,scoped_fixture_reads=False):
    data=json.loads((Path(__file__).parent/'fixtures/dr_four_arm_metadata_unverified_20261115.json').read_text(encoding='utf8'))
    assert data['scientificApproval'] is False
    value=data['wire']
    if unique_fixture_names:
        # Author distinct names only in this engineering fixture. Production
        # never renames model parameters or fills scientific values.
        for step in value['steps']:
            for op in (step.get('action',{}),step.get('measurement',{}),step.get('recording',{}).get('action',{})):
                seen=set()
                for i,p in enumerate(op.get('parameters',[])):
                    if p['name'] in seen:p['name']=p['name']+'_'+str(i)
                    seen.add(p['name'])
    if scoped_fixture_reads:
        applies={c['componentId']:set(c['appliesTo']) for c in value['components']}
        for step in value['steps']:
            groups=set(step['groups']) if 'groups' in step else {step['group']}
            step['reads']=[r for r in step['reads'] if r.get('state') not in applies
                           or groups<=applies[r['state']]]
    return value


@pytest.mark.parametrize('version',[None,True,False,0,2,'1'])
def test_envelope_has_its_own_strict_server_marker(version):
    r={**record(),'workflowMetadataEnvelopeContractVersion':version}
    assert not enabled(r) and limits(r)=={'raw':16384,'wire':8192,'expanded':8192}


@pytest.mark.parametrize('key',['workflowMetadataOutputContractVersion','structuredOutputContractVersion',
                              'executionWorkflowContractVersion','workflowMetadataRepairContractVersion'])
def test_incomplete_profile_cannot_get_larger_metadata_bounds(key):
    assert not enabled({**record(),key:0})


@pytest.mark.parametrize('dimension',['raw','wire','expanded'])
def test_utf8_limits_are_finite_and_reject_one_byte_overflow(dimension):
    r=record();cap=limits(r)
    def exact(n):return {'x':'x'*(n-len(packed({'x':''}).encode()))}
    args={'raw':'字'*(cap['raw']//3)+'x'*(cap['raw']%3),
          'wire':exact(cap['wire']),'value':exact(cap['expanded'])}
    assert not over_capacity(r,**args)
    if dimension=='raw':args['raw']+='x'
    else:args['value' if dimension=='expanded' else 'wire']['x']+='x'
    assert over_capacity(r,**args)


def test_real_complete_wire_keeps_all_arms_and_still_rejects_duplicate_parameters():
    v=wire();before=deepcopy(v);value=decode(v)
    aliases={k:'owned' for k in v['sourceRefs']}
    assert len(packed(v).encode())>8192 and len(packed(value).encode())>8192
    assert over_capacity(output_record(),packed(v),v,value)
    assert not over_capacity(record(),packed(v),v,value) and v==before
    feedback=field_feedback(v,aliases)
    assert feedback['codes']==['timeline.phase.action'] and len(feedback['issues'])==4
    assert {g for c in v['components'] for g in c['appliesTo']}=={'00','01','10','11'}


class StopAtInitializer(Exception):pass


def setup(*,envelope=True,valid_fixture=True):
    r=record() if envelope else output_record();v=wire(unique_fixture_names=valid_fixture,scoped_fixture_reads=valid_fixture)
    p=prompt_for(question='Unexecuted four-arm engineering fixture',basis={},sources={},
        evidence=[],tables={},obligations=[],version=7)
    invoke=Mock(side_effect=[{'content':packed(v),'rawContent':json.dumps(v,indent=2),'finishReason':'stop'},StopAtInitializer(),StopAtInitializer()])
    def checkpoint(value):r['state']['executionWorkflowBlueprint']=deepcopy(value)
    def run():return prepare(r,prompt=p,aliases={k:'owned' for k in v['sourceRefs']},invoke=invoke,parse=json.loads,checkpoint=checkpoint)
    return r,v,invoke,run


def test_complete_four_arm_metadata_is_retained_without_editing_and_reuses_saved_response():
    r,v,invoke,run=setup()
    for _ in range(2):
        with pytest.raises(StopAtInitializer):run()
    saved=r['state']['executionWorkflowBlueprint'];u=saved['units']['metadata']
    assert u['status']=='ready' and u['value']==decode(v) and not saved['scientificApproval']
    assert len(u['value']['phases'])==sum(2 if s['kind']=='observe' else 1 for s in v['steps'])
    assert GUIDANCE in u['request']['prompt']
    assert [c.args[0] for c in invoke.call_args_list].count('plan_workflow_meta')==1
    assert [c.args[0] for c in invoke.call_args_list][1:]==['plan_workflow_init']*2


def test_unique_names_do_not_approve_reads_from_other_arms():
    v=wire(unique_fixture_names=True)
    feedback=field_feedback(v,{k:'owned' for k in v['sourceRefs']})
    assert feedback['codes']==['timeline.input.group_leak']
    assert {g for c in v['components'] for g in c['appliesTo']}=={'00','01','10','11'}


def test_large_invalid_metadata_can_use_one_bounded_revision_without_rewriting_original():
    r=record();bad=wire();good=wire(unique_fixture_names=True,scoped_fixture_reads=True)
    p=prompt_for(question='Four-arm engineering fixture, not scientific approval',basis={},sources={},
        evidence=[],tables={},obligations=[],version=7)
    first={'content':packed(bad),'rawContent':json.dumps(bad,indent=2),'finishReason':'stop'}
    revised={'content':packed(good),'rawContent':json.dumps(good,indent=2),'finishReason':'stop'}
    invoke=Mock(side_effect=[first,revised,StopAtInitializer(),StopAtInitializer()])
    def checkpoint(value):r['state']['executionWorkflowBlueprint']=deepcopy(value)
    def run():return prepare(r,prompt=p,aliases={k:'owned' for k in bad['sourceRefs']},
        invoke=invoke,parse=json.loads,checkpoint=checkpoint)
    for _ in range(2):
        with pytest.raises(StopAtInitializer):run()
    saved=r['state']['executionWorkflowBlueprint']
    assert saved['units']['metadata']['response']==first
    assert saved['units']['metadata']['status']=='invalid_response'
    assert saved['metadataRepair']['status']=='ready' and not saved['metadataRepair']['scientificApproval']
    assert [c.args[0] for c in invoke.call_args_list].count('repair_workflow_meta')==1
    assert [c.args[0] for c in invoke.call_args_list][2:]==['plan_workflow_init']*2
    assert GUIDANCE in saved['metadataRepair']['request']['prompt']


def test_old_capacity_refusal_cannot_be_reinterpreted_under_a_new_marker():
    r,v,invoke,run=setup(envelope=False)
    with pytest.raises(DeepResearchError):run()
    saved=deepcopy(r['state']['executionWorkflowBlueprint']);assert 'unit.output_capacity' in saved['units']['metadata']['errors']
    r['workflowMetadataEnvelopeContractVersion']=1
    with pytest.raises(DeepResearchError) as e:run()
    assert e.value.code=='invalid_workflow_blueprint_state' and invoke.call_count==1
    assert r['state']['executionWorkflowBlueprint']==saved


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_marker_is_immutable_and_cannot_be_added_to_old_runs(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'runs.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Design','deferStart':True,
            'workflowMetadataEnvelopeContractVersion':replacement},start_async=False)
        assert enabled(r) and r['workflowMetadataEnvelopeContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda x:{**x,'workflowMetadataEnvelopeContractVersion':replacement})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');del old['workflowMetadataEnvelopeContractVersion'];repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run('old',lambda x:{**x,'workflowMetadataEnvelopeContractVersion':1})
    finally:facade.shutdown()
