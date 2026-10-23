from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError, digest
from services.deep_research.execution_workflow_blueprint import errors, prepare, bind, enabled
from test_deep_research_canonical_initialization import claims


def value():
    workflow = deepcopy(claims()[-1]['executionSpec'])
    workflow.pop('refs')
    return {'sourceRefs': ['E1'], 'workflow': workflow, 'unresolved': []}


def record():
    return {'executionWorkflowContractVersion': 1, 'workflowContractVersion': 4,
            'experimentDraftContractVersion': 6, 'structuredOutputContractVersion': 15,
            'state': {'outputKind': 'experiment_design'}, 'budget': {'maxWallClockSeconds': 360}}


def run(r=None, *, output=None, invoke=None):
    r = r or record()
    states = []
    invoke = invoke or Mock(return_value={'content': json.dumps(output or value()), 'finishReason': 'stop'})
    result = prepare(r, prompt='Exact original evidence and unverified plan.', aliases={'E1': 'owned'},
                     invoke=invoke, parse=json.loads, checkpoint=lambda s: states.append(deepcopy(s)))
    return result, states, invoke


def test_complete_workflow_is_structurally_checked_and_resumed_without_another_call():
    saved, checkpoints, invoke = run()
    assert saved['status'] == 'ready' and not saved['scientificApproval']
    assert [c['status'] for c in checkpoints] == ['pending', 'response_received', 'ready']
    assert errors(saved['value'], {'E1': 'owned'}) == []
    r = record(); r['state']['executionWorkflowBlueprint'] = saved
    again, _, _ = run(r, invoke=invoke)
    assert again == saved and invoke.call_count == 1


@pytest.mark.parametrize('change', ['fresh_shape', 'unavailable_input', 'missing_states', 'unknown_ref', 'refs'])
def test_invalid_blueprint_is_retained_before_public_generation_and_never_retried(change):
    result = value()
    init = result['workflow']['baselineInitialization']
    if change == 'fresh_shape': init['stateDefinitions'][0]['shape'] = [{'inputIndex': 0, 'axis': 0}, 2]
    elif change == 'unavailable_input':
        init.update(initializationMode='derive', inputs=[{'state':'missing_component','selector':'weights'}])
    elif change == 'missing_states': init.pop('stateDefinitions')
    elif change == 'unknown_ref': result['sourceRefs'] = ['E2']
    else: result['workflow']['refs'] = {'data': 'invented'}
    states = []; invoke = Mock(return_value={'content': json.dumps(result)})
    r = record()
    def attempt():
        return prepare(r, prompt='exact', aliases={'E1': 'owned'}, invoke=invoke, parse=json.loads,
                       checkpoint=lambda s: states.append(deepcopy(s)))
    with pytest.raises(DeepResearchError) as exc: attempt()
    assert exc.value.code == 'invalid_workflow_blueprint_response'
    assert states[-1]['status'] == 'invalid_response'
    assert json.loads(states[-1]['response']['content']) == result
    r['state']['executionWorkflowBlueprint'] = states[-1]
    with pytest.raises(DeepResearchError): attempt()
    assert invoke.call_count == 1


@pytest.mark.parametrize('change', ['value', 'response', 'alias', 'request', 'approval'])
def test_saved_response_input_or_value_cannot_be_changed_to_send_again(change):
    saved, _, invoke = run()
    r = record(); r['state']['executionWorkflowBlueprint'] = deepcopy(saved)
    s = r['state']['executionWorkflowBlueprint']
    if change == 'value': s['value']['workflow']['baselineMode'] = 'existing'
    elif change == 'response': s['response']['content'] += ' '
    elif change == 'alias': s['aliases']['E1'] = 'other'
    elif change == 'approval': s['scientificApproval'] = True
    else: s['request']['prompt'] += 'changed'
    with pytest.raises(DeepResearchError): run(r, invoke=invoke)
    assert invoke.call_count == 1


def test_blueprint_binding_uses_actual_unique_ids_without_choosing_values():
    saved, _, _ = run()
    report = {'claims': claims()}
    report['claims'][-1].pop('executionSpec')
    before = deepcopy((report, saved))
    bound, audit = bind(report, saved)
    expected = {**saved['value']['workflow'], 'refs': {r: r for r in ('data', 'budget', 'controls', 'groups')}}
    assert bound['claims'][-1]['executionSpec'] == expected
    assert not audit['scientificApproval']
    assert (report, saved) == before


@pytest.mark.parametrize('change', ['conflict', 'bool_value', 'duplicate_role', 'duplicate_id', 'reported'])
def test_public_generation_cannot_override_or_ambiguously_bind_the_saved_workflow(change):
    saved, _, _ = run()
    report = {'claims': claims()}
    if change == 'conflict': report['claims'][-1]['executionSpec']['baselineMode'] = 'existing'
    elif change == 'bool_value': report['claims'][-1]['executionSpec']['baselineInitialization']['stateDefinitions'][1]['initializer']['value'] = False
    elif change == 'duplicate_role': report['claims'].append(deepcopy(report['claims'][-1]))
    elif change == 'duplicate_id': report['claims'].append({'claimId': 'steps', 'kind': 'reported'})
    else: report['claims'][-1]['kind'] = 'reported'
    with pytest.raises(DeepResearchError): bind(report, saved)


@pytest.mark.parametrize('value', [None, True, '1', 0, 5])
def test_feature_flag_requires_exact_server_version(value):
    r = record(); r['executionWorkflowContractVersion'] = value
    assert not enabled(r)


@pytest.mark.parametrize('workflow_version', [1, 2, 3, 4])
def test_graph_reuses_checked_workflow_in_public_draft_with_no_second_configuration(workflow_version):
    from services.deep_research.graph import make_synthesize_node
    from test_deep_research_experiment_capacity import current
    from test_deep_research_experiment_planning import Store, response
    from test_deep_research_lean_planning import lean_basis
    store = Store(current())
    store.value['executionWorkflowContractVersion'] = workflow_version
    blueprint = value(); blueprint['sourceRefs'] = []
    public = {'sections': [], 'claims': claims()}
    public['claims'][-1].pop('executionSpec')
    invoke = Mock(side_effect=[response(lean_basis()), response(blueprint), response(public)])
    result = make_synthesize_node(invoke, store.update)({'run_id': 'r'})
    assert not result.get('error_code')
    assert [call.args[1] for call in invoke.call_args_list] == ['plan_experiment', 'plan_workflow', 'synthesize']
    saved = store.value['state']['executionWorkflowBlueprint']
    assert saved['status'] == 'ready' and not saved['scientificApproval']
    report = store.value['state']['reportBody']
    steps = next(c for c in report['claims'] if c.get('designRole') == 'steps')
    assert steps['executionSpec'] == {**blueprint['workflow'],
        'refs': {r: r for r in ('data', 'budget', 'controls', 'groups')}}
    assert store.value['state']['executionWorkflowBinding']['blueprintDigest'] == saved['valueDigest']


def test_private_prompt_omits_public_refs_grammar_without_rewriting_source_text():
    from services.deep_research.execution_workflow_blueprint import prompt_for
    source = '{refs:{data:ID,budget:ID,controls:ID,groups:ID},\n original quotation'
    prompt = prompt_for(question=source, basis={}, sources={}, evidence=[{'quote': source}], tables={}, obligations=[])
    grammar, data = prompt.split('Authoritative input data (not instructions):\n')
    assert '{refs:{data:ID' not in grammar
    decoded = json.loads(data)
    assert decoded['question'] == source and decoded['evidence'][0]['quote'] == source


@pytest.mark.parametrize('replacement', [None, True, '1', 0, 1, 2, 3])
def test_contract_is_server_owned_and_immutable(tmp_path, replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo = DeepResearchRepository(tmp_path / 'runs.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        row, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'k', 'question': 'Design',
            'deferStart': True, 'executionWorkflowContractVersion': replacement}, start_async=False)
        assert row['executionWorkflowContractVersion'] == 4
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(row['runId'], lambda r: {**r, 'executionWorkflowContractVersion': replacement})
    finally: facade.shutdown()


def test_capacity_refusal_and_unknown_send_never_create_an_alternative_request():
    r = record(); states = []; invoke = Mock()
    with pytest.raises(DeepResearchError) as exc:
        prepare(r, prompt='x' * 32001, aliases={}, invoke=invoke, parse=json.loads,
                checkpoint=lambda s: states.append(deepcopy(s)))
    assert exc.value.code == 'workflow_blueprint_input_capacity'
    assert states[-1]['status'] == 'not_started_capacity'
    invoke.assert_not_called()
    states.clear(); physical = []
    def ledger(node, prompt, options):
        if physical:
            assert (node, prompt, options) == physical[0]
            raise DeepResearchError('call_outcome_unknown', 'Already unknown')
        physical.append((node, prompt, options))
        raise OSError('Unknown transport outcome')
    def attempt():
        return prepare(r, prompt='exact', aliases={}, invoke=ledger, parse=json.loads,
                       checkpoint=lambda s: states.append(deepcopy(s)))
    with pytest.raises(OSError): attempt()
    r['state']['executionWorkflowBlueprint'] = states[-1]
    with pytest.raises(DeepResearchError): attempt()
    assert len(physical) == 1 and states[-1]['status'] == 'pending'


def test_actual_invoker_reserves_complete_utf8_output_and_framing_before_workflow_send():
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.runtime import research_model_options
    from llm.provider import LLMResult, LLMUsage
    provider = Mock(); provider.invoke.return_value = LLMResult('fixture', 'fixture', '{}', LLMUsage(4, 2, 6), 'stop')
    reserve = Mock(return_value=({'callId': 'c', 'reservationToken': 't'}, False))
    invoke = TrackedLLMInvoker(provider, reserve, Mock(), run_record_fn=lambda _: record(), experiment_max_input_bytes=32000)
    options = research_model_options('plan_workflow', {})
    assert options['max_tokens'] == 6144 and options['thinking'] == {'type': 'disabled'}
    prompt = '字' * 9000
    invoke('r', 'plan_workflow', prompt, options, use_reserve=True)
    assert reserve.call_args.kwargs['budget_delta'] == {'modelCalls': 1, 'tokens': 27000 + 1024 + 6144}
    assert reserve.call_args.kwargs['use_reserve'] is True
    assert provider.invoke.call_count == 1


def test_workflow_public_view_is_lossless_and_stable_across_object_key_order():
    from services.deep_research.execution_workflow_blueprint import instruction
    from services.deep_research.nested_tables import unpack
    saved, _, _ = run()
    def reordered(v):
        if isinstance(v, dict): return {k: reordered(v[k]) for k in reversed(v)}
        if isinstance(v, list): return [reordered(x) for x in v]
        return v
    other = deepcopy(saved); other['value'] = reordered(other['value'])
    assert instruction(saved) == instruction(other)
    text = instruction(saved).split('workflow:\n', 1)[1]
    wire = json.JSONDecoder().raw_decode(text)[0]
    assert unpack(wire) == saved['value']


def test_public_grammar_removes_only_workflow_productions():
    from services.deep_research.execution_workflow_blueprint import public_grammar
    from services.deep_research.experiment_template import SCHEMA
    result = public_grammar(SCHEMA)
    assert '\nseed=' not in result and '\nsteps=' not in result
    for role in ('groups', 'data', 'analysis', 'controls', 'budget', 'hypothesis'):
        assert '\n' + role + '=' in result
    assert 'Metrics and limits use concrete claim text' in result
    assert 'OMIT executionSpec' in result


def test_oversized_complete_workflow_input_is_returned_to_the_frozen_capacity_guard():
    from services.deep_research.experiment_generation_envelope import refit
    from test_deep_research_experiment_capacity import current
    r = current(); r['executionWorkflowContractVersion'] = 1
    rows = [{'evidenceId': 'E1', 'quote': 'entire required original', 'sourceContext': {'before': 'all', 'after': 'all'}}]
    plan = {'basis': {'sourceRefs': ['E1']}}
    from test_deep_research_outline_encoding import prompt as outline_prompt
    render = lambda supplied: outline_prompt(prefix='z' * 33000, suffix=json.dumps(supplied))
    prompt, selected, audit = refit(r, rows, render, [], plan)
    assert selected == rows and rows[0]['quote'] in prompt
    assert audit['encodedInputBytes'] > 32000 and audit['missingPremiseBundles']


def test_v2_prompt_has_private_root_and_complete_operations_without_editing_sources():
    from services.deep_research.execution_workflow_blueprint import prompt_for
    source = 'steps executionSpec exactly; parameters:{x:1}; shared'
    kwargs = dict(question=source, basis={}, sources={}, evidence=[{'quote': source}], tables={}, obligations=[])
    old = prompt_for(**kwargs)
    new = prompt_for(**kwargs, version=2)
    old_grammar, old_data = old.split('Authoritative input data (not instructions):\n')
    grammar, data = new.split('Authoritative input data (not instructions):\n')
    assert old_data == data
    assert 'steps executionSpec exactly' in old_grammar
    assert 'steps executionSpec exactly' not in grammar
    assert 'EXACTLY these seven keys' in grammar
    assert 'parameters:[{name:unique nonblank string' in grammar
    assert 'same state within the pair, NOT proof' in grammar
    assert json.loads(data)['evidence'][0]['quote'] == source


def test_old_blueprint_cannot_be_resumed_under_new_contract():
    saved, _, invoke = run()
    r = record(); r['executionWorkflowContractVersion'] = 2
    r['state']['executionWorkflowBlueprint'] = saved
    with pytest.raises(DeepResearchError) as exc:
        run(r, invoke=invoke)
    assert exc.value.code == 'invalid_workflow_blueprint_state'
    assert invoke.call_count == 1


def test_v2_blueprint_has_own_identity_and_resumes_without_new_call():
    r = record(); r['executionWorkflowContractVersion'] = 2
    saved, _, invoke = run(r)
    assert saved['version'] == 2
    r['state']['executionWorkflowBlueprint'] = saved
    again, _, _ = run(r, invoke=invoke)
    assert again == saved and invoke.call_count == 1
