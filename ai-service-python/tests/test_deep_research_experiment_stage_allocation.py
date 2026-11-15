"""Stage admission preserves required premises and the unchanged final guard."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.experiment_stage_allocation import enabled
from services.deep_research.graph import make_synthesize_node
from services.deep_research.scientific_outline import NODE
from test_deep_research_scientific_outline import record
from test_deep_research_experiment_planning import Store


def current():
    return {**record(), 'experimentStageAllocationContractVersion': 1}


@pytest.mark.parametrize('version', [None, True, False, 0, 2, '1'])
def test_only_new_server_marker_enables_stage_sizing(version):
    assert not enabled({**current(), 'experimentStageAllocationContractVersion': version})


@pytest.mark.parametrize('key', ['scientificOutlineContractVersion', 'experimentInputContractVersion',
                                 'experimentGenerationEnvelopeContractVersion'])
def test_partial_contract_cannot_enable_stage_allocation(key):
    assert enabled(current())
    assert not enabled({**current(), key: 0})


class StopBeforeModel(Exception):
    pass


@pytest.mark.parametrize('stage', [False, True])
def test_allocation_measures_actual_first_request_and_preserves_legacy_audit(stage):
    r=current()
    if not stage:r.pop('experimentStageAllocationContractVersion')
    store=Store(r);before=deepcopy(r['state']['evidence'])
    invoke=Mock(side_effect=StopBeforeModel)
    with pytest.raises(StopBeforeModel):make_synthesize_node(invoke,store.update)({'run_id': 'r'})
    assert invoke.call_args.args[1]==NODE and invoke.call_count==1
    allocation=store.value['state']['synthesisPremiseAllocation']
    request=store.value['state']['experimentPlanning']['request']['prompt']
    assert request==invoke.call_args.args[2]
    assert before==store.value['state']['evidence']
    assert before[0]['quote'] in request
    assert not allocation['missingPremiseBundles']
    if stage:
        assert allocation['inputBytes']==len(request.encode('utf8'))
        assert allocation['allocationNode']==NODE
        assert allocation['generationTemplateIsDispatched'] is False
        assert 'planningSlotReservedBytes' not in allocation
        assert allocation['inputBytes']<=allocation['maxPromptBytes']<=32000
    else:
        assert allocation['planningSlotReservedBytes']==4000
        assert 'stageAllocationContractVersion' not in allocation


def test_unfittable_complete_required_source_still_stops_before_call():
    r=current();r['state']['evidence'][0]['quote']='We define the operation as '+('原文不允许截断 '*9000)
    before=deepcopy(r['state']['evidence']);store=Store(r);invoke=Mock()
    assert make_synthesize_node(invoke,store.update)({'run_id':'r'})=={'error_code':'synthesis_evidence_capacity'}
    invoke.assert_not_called()
    assert store.value['state']['evidence']==before
    assert store.value['state']['synthesisPremiseAllocation']['missingPremiseBundles']


def test_complete_required_source_can_fit_actual_stage_when_future_template_cannot():
    original=current()
    original['state']['evidence'][0]['quote']='We define the operation as '+('x'*20000)
    old=deepcopy(original);old.pop('experimentStageAllocationContractVersion')
    legacy=Store(old);old_invoke=Mock()
    assert make_synthesize_node(old_invoke,legacy.update)({'run_id':'r'})=={'error_code':'synthesis_evidence_capacity'}
    old_invoke.assert_not_called()
    store=Store(original);invoke=Mock(side_effect=StopBeforeModel)
    with pytest.raises(StopBeforeModel):make_synthesize_node(invoke,store.update)({'run_id':'r'})
    assert invoke.call_args.args[1]==NODE
    assert original['state']['evidence'][0]['quote'] in invoke.call_args.args[2]
    assert len(invoke.call_args.args[2].encode('utf8'))<=32000
    assert not store.value['state']['synthesisPremiseAllocation']['missingPremiseBundles']
    assert store.value['state']['evidence']==original['state']['evidence']


def test_final_generation_still_keeps_every_required_reference_and_refuses_oversize():
    from services.deep_research.experiment_generation_envelope import refit
    from services.deep_research.experiment_capacity import input_limit
    from test_deep_research_generation_envelope import example
    from test_deep_research_outline_encoding import prompt
    r=current();rows,plan,bundles=example();before=deepcopy((rows,plan,bundles))
    # The final generation request exceeds the same cap even with required rows only.
    render=lambda selected:prompt(prefix='x'*32000+json.dumps(selected))
    body,selected,audit=refit(r,rows,render,bundles,plan)
    assert input_limit(r)==32000 and audit['maxInputBytes']==32000
    assert audit['missingPremiseBundles'] and audit['encodedInputBytes']>32000
    required={eid for b in bundles for eid in b['evidenceIds']}|set(plan['basis']['sourceRefs'])
    assert required<={row['evidenceId'] for row in selected}
    assert len(body.encode())>32000 and before==(rows,plan,bundles)


@pytest.mark.parametrize('replacement', [None, True, '1', 0, 2])
def test_server_owns_marker_and_history_cannot_be_opted_in(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'runs.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Design','outputKind':'experiment_design',
            'experimentStageAllocationContractVersion':replacement,'deferStart':True},start_async=False)
        assert r['experimentStageAllocationContractVersion']==1 and enabled(r)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda value:{**value,'experimentStageAllocationContractVersion':replacement})
        legacy=deepcopy(r);legacy.update(runId='old',idempotencyKey='old')
        del legacy['experimentStageAllocationContractVersion'];repo.create_run(legacy)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run('old',lambda value:{**value,'experimentStageAllocationContractVersion':1})
    finally:facade.shutdown()
