from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.configuration_consistency import align_grammar,align_repair,modern,GENERATION2,PLANNING2
from services.deep_research.experiment_template import SCHEMA
from services.deep_research.state_initialization import state_definition_errors
from services.deep_research.repair import repair_rejected
from services.deep_research.contracts import DeepResearchError
from test_deep_research_shared_experiment_repair import inputs
from test_deep_research_experiment_representation import prepare,wrapped_claims


@pytest.mark.parametrize('version',[None,True,False,'2',0,1,3])
def test_old_wrong_type_and_future_contracts_keep_exact_grammar_and_repair(version):
    assert not modern(version) and align_grammar(SCHEMA,version)==SCHEMA
    assert align_repair('Any original prompt',version)=='Any original prompt'


def test_new_grammar_matches_existing_state_rules_and_retains_all_role_fields():
    new=align_grammar(SCHEMA,2)
    assert 'Unmatched confounds budgets.' not in new and 'whole-stage cost tradeoffs' in new
    assert 'operation.rule requires NONEMPTY' in new and 'parameter-free creation/group' in new
    state={'name':'positions','dtype':'float32','shape':[3],
        'initializer':{'mode':'operation','inputIndices':[0],'rule':{'action':'copy','parameters':[]}}}
    before=deepcopy(state)
    assert 'states.operation_rule' in state_definition_errors([state],[{'state':'baseline','selector':'positions'}])
    assert state==before
    state['initializer']['rule']['parameters']=[{'name':'transform','type':'choice','value':'identity'}]
    assert not state_definition_errors([state],[{'state':'baseline','selector':'positions'}])
    for role in ('groups','data','controls','budget','steps','analysis','hypothesis'):
        assert (role+'=') in new
    assert align_grammar(SCHEMA,1)==SCHEMA  # No mutation of the legacy constant.


def test_new_graph_wires_planning_and_full_generation_without_changing_source_permissions():
    from services.deep_research.graph import make_synthesize_node
    from test_deep_research_lean_planning import record,lean_basis
    from test_deep_research_experiment_planning import Store,response
    current=record();current['configurationConsistencyContractVersion']=2;store=Store(current)
    body={'sections':[],'claims':wrapped_claims()};raw=deepcopy(body)
    invoke=Mock(side_effect=[response(lean_basis()),response(body)])
    result=make_synthesize_node(invoke,store.update)({'run_id':'r'})
    assert 'error_code' not in result and body==raw and invoke.call_count==2
    plan,draft=[call.args[2] for call in invoke.call_args_list]
    assert PLANNING2 in plan and GENERATION2 in draft and 'operation.rule requires NONEMPTY' in draft
    assert 'Unmatched confounds budgets.' not in draft
    assert len(draft.encode())<=24000
    assert store.value['state']['reportBody']['claims']


def test_repair_aligns_cost_scope_state_rules_and_prose_without_altering_permissions():
    old=prepare();new=prepare(configuration_consistency_version=2)
    assert old['allowed']==new['allowed'] and old['originals']==new['originals']
    assert 'operation.rule needs NONEMPTY' in new['prompt']
    assert 'Fix prose/conditions WITH configs.' in new['prompt']
    assert 'whole-stage tradeoffs may use finite unmatched cost' in new['prompt']
    assert len(new['prompt'].encode())<=24000


def test_repair_never_rewrites_grammar_phrases_embedded_in_original_claims_or_sources():
    packet=json.dumps({'text':'Unmatched confounds budgets. Scalar shape is []; constants broadcast compatibly;',
        'conditions':{'quote':'Unmatched confounds budgets.'}},ensure_ascii=False)
    assert align_repair(packet,2)==packet


def test_repair_transforms_only_its_system_policy_even_when_question_and_original_quote_it():
    from services.deep_research.experiment_nested_prompt import DRAFTING_POLICY
    from services.deep_research.repair import _prepare_repair
    report,checks,evidence=inputs();report['claims'][0]['text']=DRAFTING_POLICY
    question='Explain this policy verbatim: '+DRAFTING_POLICY
    new=_prepare_repair(report,checks,evidence,question,experimental_intent=3,
        shared_experiment_schema=True,experimental_edits=True,experimental_diagnostics=True,
        experimental_nested_tables=True,configuration_consistency_version=2)
    assert question in new['prompt'] and json.dumps(DRAFTING_POLICY,ensure_ascii=False) in new['prompt']
    assert 'Fix prose/conditions WITH configs.' in new['prompt']


def test_pending_repair_cannot_switch_generation_policy_to_resend():
    report,checks,evidence=inputs();saved=[];invoke=Mock(side_effect=OSError('unknown'))
    args=dict(experimental_intent=3,shared_experiment_schema=True,experimental_edits=True,
        experimental_diagnostics=True,experimental_nested_tables=True,experimental_representation=True)
    with pytest.raises(OSError):
        repair_rejected(report,checks,evidence,'Q',Mock(),json.loads,**args,
            invoke_request=invoke,checkpoint=lambda s:saved.append(deepcopy(s)))
    frozen=deepcopy(saved[-1]);invoke.reset_mock()
    with pytest.raises(DeepResearchError,match='原始输入'):
        repair_rejected(report,checks,evidence,'Q',Mock(),json.loads,**args,
            configuration_consistency_version=2,invoke_request=invoke,batch_state=frozen)
    invoke.assert_not_called();assert frozen==saved[-1]
