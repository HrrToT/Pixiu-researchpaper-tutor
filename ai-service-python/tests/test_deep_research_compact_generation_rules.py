from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.experiment_capacity import reserved_basis_bytes, input_limit
from services.deep_research.experiment_generation_envelope import enabled
from services.deep_research.graph import make_synthesize_node
from test_deep_research_experiment_planning import Store, response
from test_deep_research_blueprint_shared_wire import prepare
from test_deep_research_request_sized_blueprint import current as old_record, larger
from services.deep_research.experiment_blueprint import columns


def legacy():
    record=old_record()
    record.update(experimentInputContractVersion=1,outputKind='experiment_design')
    return record


def current():
    record=legacy()
    record.update(experimentGenerationEnvelopeContractVersion=2,
        experimentExecutionGuidanceContractVersion=2,structuredOutputContractVersion=13)
    return record


def test_reserve_the_full_admissible_plan_before_fitting_evidence():
    assert enabled(current())
    assert reserved_basis_bytes(current()) == 8192
    assert reserved_basis_bytes(legacy()) == 4000
    assert input_limit(current()) == input_limit(legacy()) == 32000


@pytest.mark.parametrize('key,value', [
    ('experimentPlanEncodingContractVersion',6),
    ('structuredOutputContractVersion',12),
    ('experimentExecutionGuidanceContractVersion',1),
])
def test_compact_generation_requires_complete_compatible_profile(key,value):
    record=current();record[key]=value
    assert not enabled(record)


@pytest.mark.parametrize('generation_version',[2,3])
def test_complete_large_plan_and_exact_source_quote_fit_without_extra_model_calls(generation_version):
    record=current()
    record['experimentGenerationEnvelopeContractVersion']=generation_version
    quote=record['state']['evidence'][0]['quote']
    store=Store(record)
    invoke=Mock(side_effect=[response(columns(larger())),response({'sections':[],'claims':[]})])
    make_synthesize_node(invoke,store.update)({'run_id':'r'})
    assert invoke.call_count == 2
    body=invoke.call_args_list[1].args[2]
    assert len(body.encode('utf8'))<=32000
    import json
    assert json.dumps(quote,ensure_ascii=False)[1:-1] in body
    assert store.value['state']['experimentPlanning']['basis']==larger()
    assert not store.value['state']['generationPremiseAllocation']['missingPremiseBundles']
    assert ('Group IDs are binary STRINGS' in body)==(generation_version==3)


def test_unknown_legacy_plan_cannot_be_resent_with_new_generation_policy():
    store=Store(legacy());invoke=Mock(side_effect=OSError('unknown'))
    with pytest.raises(OSError):prepare(store,invoke)
    frozen=deepcopy(store.value['state']['experimentPlanning'])
    store.value.update(current());store.value['state']['experimentPlanning']=frozen
    invoke.reset_mock()
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    invoke.assert_not_called()
    assert store.value['state']['experimentPlanning']==frozen


def test_instruction_like_source_text_is_never_rewritten_by_compaction():
    import json
    from services.deep_research.configuration_consistency import GENERATION2
    record=current()
    record['state']['evidence'][0]['quote']=GENERATION2
    store=Store(record)
    invoke=Mock(side_effect=[response(columns(larger())),response({'sections':[],'claims':[]})])
    make_synthesize_node(invoke,store.update)({'run_id':'r'})
    body=invoke.call_args_list[1].args[2]
    assert json.dumps(GENERATION2,ensure_ascii=False)[1:-1] in body


def test_unknown_version2_plan_cannot_change_to_version3_even_for_same_prompt():
    store=Store(current());invoke=Mock(side_effect=OSError('unknown'))
    with pytest.raises(OSError):prepare(store,invoke)
    frozen=deepcopy(store.value['state']['experimentPlanning'])
    store.value['experimentGenerationEnvelopeContractVersion']=3
    invoke.reset_mock()
    with pytest.raises(DeepResearchError):prepare(store,invoke)
    invoke.assert_not_called()
    assert store.value['state']['experimentPlanning']==frozen
