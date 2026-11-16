"""Selection/dependency guidance is versioned without modifying inputs or schema."""
from copy import deepcopy
import json

import pytest

from services.deep_research.workflow_initialization_numeric import MARKER, POLICY, SELECTION_POLICY, policy
from services.deep_research.workflow_units import INIT, unit_prompt
from services.deep_research.contracts import DeepResearchError
import test_deep_research_initialization_numeric as numeric_tests
import test_deep_research_initialization_structured as structured_tests
import test_deep_research_workflow_initialization_context as context_tests
from test_deep_research_workflow_metadata_ordered_integration import input_value


@pytest.mark.parametrize('version',[None,True,0,3,'2'])
def test_unsupported_numeric_policy_cannot_change_prompt(version):
    with pytest.raises(ValueError):policy(version)


def test_input_values_and_legacy_numeric_policy_are_unchanged():
    source=numeric_tests.decision_tests.value()['authoritativeInput'];ctx=context_tests.context()
    args=dict(node=INIT,context=ctx,version=7,scoped_initialization_input=True,
        initialization_context_version=2,initialization_recipe=True,structured_initialization=True,
        decision_input=True,numeric_initialization=True)
    old=unit_prompt(json.dumps(source),**args);new=unit_prompt(json.dumps(source),**args,numeric_initialization_version=2)
    assert old.startswith(POLICY) and new.startswith(POLICY+SELECTION_POLICY)
    assert policy(1)==POLICY and input_value(new)==input_value(old)


def test_complete_workflow_reopens_without_resending_or_rewriting_values():
    r,invoke,run=structured_tests.setup();r.update({numeric_tests.decision_tests.MARKER:1,MARKER:2})
    saved=run();assert saved['status']=='ready' and saved['request']['initializationNumericStateContract']==2
    for call in invoke.call_args_list:
        if call.args[0]==INIT:assert SELECTION_POLICY in call.args[1]
        else:assert SELECTION_POLICY not in call.args[1]
    count=invoke.call_count;assert run()==saved and invoke.call_count==count


def test_v1_units_cannot_be_reinterpreted_as_v2():
    r,invoke,run=structured_tests.setup();r.update({numeric_tests.decision_tests.MARKER:1,MARKER:1})
    run();count=invoke.call_count;r[MARKER]=2
    with pytest.raises(DeepResearchError,match='原始输入不一致'):run()
    assert invoke.call_count==count


def test_only_repair_keeps_actual_invalid_definition_and_v2_guidance():
    r,invoke,run=structured_tests.setup();r.update({numeric_tests.decision_tests.MARKER:1,MARKER:2})
    calls=list(invoke.side_effect);bad=deepcopy(calls[-1]);wire=json.loads(bad['content'])
    wire['initialization']['stateDefinitions'][0]['shape']=[{'inputIndex':0,'axis':9}]
    bad['content']=json.dumps(wire);calls[-1]=bad;invoke.side_effect=calls+[bad]
    with pytest.raises(DeepResearchError):run()
    fix=r['state']['executionWorkflowBlueprint']['initializationRepair']
    assert SELECTION_POLICY in fix['request']['prompt']
    assert input_value(fix['request']['prompt'])['invalidInitialization']==wire
    count=invoke.call_count
    with pytest.raises(DeepResearchError):run()
    assert invoke.call_count==count


@pytest.mark.parametrize('scenario',['success','unknown','budget'])
def test_v2_http_capacity_budget_and_unknown_no_resend(tmp_path,monkeypatch,scenario):
    def record():return {**numeric_tests.record(),MARKER:2}
    monkeypatch.setattr(context_tests,'record',record)
    context_tests.test_actual_http_precise_schema_budget_and_unknown_identity(tmp_path,monkeypatch,scenario)
