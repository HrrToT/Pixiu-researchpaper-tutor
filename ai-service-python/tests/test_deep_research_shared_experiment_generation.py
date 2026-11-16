from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError, digest, UnknownCallError
from services.deep_research.shared_experiment_generation import MARKER, NODE, build, prepare, enabled, descriptor
from services.deep_research.design_drafting import synthesis_obligations
from services.deep_research.selection import surrounding_context
from test_deep_research_shared_experiment_plan import proposal


def context():
    from test_deep_research_comparison_intent import record
    from services.deep_research.verification import make_evidence
    r = record(); r.update(runId='r', taskId='t', question='Design a paired two-factor experiment.', startedAt=None)
    r[MARKER] = 1
    ev = make_evidence({'workId':'owned', 'versionId':'v1', 'contentHash':'hash', 'accessLevel':'fulltext'},
        'An exact public source statement.', 'An exact public source statement.', location={}, obligation_ids=['G1'])
    r['state'].update(outputKind='experiment_design', evidence=[ev], plan=[{'itemId':'design',
        'obligations':[{'obligationId':'G1', 'question':r['question'], 'purpose':'answer_requirement',
            'completionCriteria':[{'criterionId':'complete', 'requirement':'Complete paired protocol', 'responseType':'explanation'}]}]}])
    row = {'evidenceId':'E1', 'source':'P1', 'quote':ev['quote'], 'sourceContext':surrounding_context(ev),
           'accessLevel':ev['accessLevel'], 'location':ev.get('location', {}), 'obligations':['G1']}
    data = {'question':r['question'], 'requirements':synthesis_obligations(r['state']['plan']),
            'sources':{'P1':{'workId':'owned', 'title':'Fixture publication'}}, 'evidence':[row], 'tables':{}}
    return r, data, {'E1':ev['evidenceId']}


def response(value=None, **kwargs):
    return {'content':json.dumps(proposal() if value is None else value), 'finishReason':'stop', **kwargs}


def harness(r):
    current = deepcopy(r); states = []
    def checkpoint(v):
        current['state']['sharedExperimentGeneration'] = deepcopy(v); states.append(deepcopy(v))
    return current, states, checkpoint


@pytest.mark.parametrize('version', [None, 0, True, '1', 2])
def test_legacy_and_invalid_policy_do_not_select_new_transport(version):
    from services.deep_research.planning_transport import enabled as transport_enabled
    r, data, aliases = context(); r[MARKER] = version
    assert not enabled(r) and not transport_enabled(r, NODE)
    with pytest.raises(ValueError): build(r, data, aliases)


def test_single_generation_is_durable_unchecked_and_reused_without_second_send():
    r, data, aliases = context(); current, states, checkpoint = harness(r); invoke = Mock(return_value=response())
    result = prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert [s['status'] for s in states] == ['pending', 'response_received', 'awaiting_scientific_review']
    assert result['scientificApproval'] is False and result['boundProposal']['scientificApproval'] is False
    assert result['status'] == 'awaiting_scientific_review' and result['response'] == response()
    assert prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint) == result
    assert invoke.call_count == 1 and 'reportBody' not in current['state']


@pytest.mark.parametrize('mutation', ['question', 'goal', 'quote', 'context', 'source', 'publication', 'location', 'alias', 'table'])
def test_changed_original_context_stops_before_request_or_checkpoint(mutation):
    r, data, aliases = context(); invoke = Mock(); saved = []
    if mutation == 'question': data['question'] += ' changed'
    elif mutation == 'goal': data['requirements'][0]['question'] += ' changed'
    elif mutation == 'quote': data['evidence'][0]['quote'] += ' invented'
    elif mutation == 'context': data['evidence'][0]['sourceContext'] = {'before':'invented', 'after':'', 'truncated':False}
    elif mutation == 'source': data['sources']['P1']['workId'] = 'foreign'
    elif mutation == 'publication': data['sources']['P1']['publicationIdentity'] = {'revision':'v99'}
    elif mutation == 'location': data['evidence'][0]['location'] = {'page':999}
    elif mutation == 'alias': aliases['E2'] = aliases['E1']
    else: data['evidence'][0]['tableData'] = {'rows':['invented']}
    with pytest.raises(ValueError): prepare(r, data, aliases, invoke=invoke, checkpoint=saved.append)
    invoke.assert_not_called(); assert not saved


def test_native_schema_and_actual_input_window_are_counted_before_send():
    r, data, aliases = context()
    # Change both authoritative source and wire row. Repetitions are not used:
    # string sharing cannot hide this unique source's size.
    large = ''.join(chr(0x4e00+i) for i in range(14000))
    r['state']['evidence'][0]['quote'] = large; data['evidence'][0]['quote'] = large
    r['state']['evidence'][0]['sourceContext'] = large
    data['evidence'][0]['sourceContext'] = surrounding_context(r['state']['evidence'][0])
    invoke = Mock(); saved = []
    with pytest.raises(DeepResearchError) as error: prepare(r, data, aliases, invoke=invoke, checkpoint=saved.append)
    assert error.value.code == 'shared_experiment_input_capacity'
    assert saved[-1]['inputBytes'] > 32000 and saved[-1]['transportOverheadBytes'] > 9000
    invoke.assert_not_called()


def test_call_floor_counts_both_spent_pools_and_stops_without_waiving_reviews():
    r, data, aliases = context(); r['budget'].update(modelCalls=10, reservedModelCalls=3)
    saved = []; invoke = Mock()
    assert prepare(r, data, aliases, invoke=invoke, checkpoint=saved.append) is None
    assert saved[-1]['status'] == 'not_started_budget' and saved[-1]['remainingModelCallsAtPreparation'] == 5
    invoke.assert_not_called()


@pytest.mark.parametrize('kind', ['length', 'duplicate', 'invalid_plan', 'malformed', 'missing_finish'])
def test_invalid_reply_is_saved_and_never_auto_retried(kind):
    r, data, aliases = context(); current, states, checkpoint = harness(r); reply = response()
    if kind == 'length': reply['finishReason'] = 'length'
    elif kind == 'duplicate': reply['content'] = reply['content'].replace('"version": 1', '"version": 1,"version":1', 1)
    elif kind == 'invalid_plan':
        p = proposal(); p['groups'][0]['levels']['A'] = 1; reply = response(p)
    elif kind == 'missing_finish': reply.pop('finishReason')
    else: reply['content'] = '{'
    invoke = Mock(return_value=reply)
    for _ in range(2):
        with pytest.raises(DeepResearchError) as error: prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
        assert error.value.code == 'invalid_shared_experiment_response'
    assert invoke.call_count == 1 and states[-1]['status'] == 'invalid_response'
    assert states[-1]['response'] == reply and not states[-1].get('boundProposal')


def test_unknown_invocation_is_not_reentered_on_resume():
    r, data, aliases = context(); current, states, checkpoint = harness(r)
    invoke = Mock(side_effect=UnknownCallError('unknown-original'))
    with pytest.raises(UnknownCallError): prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    with pytest.raises(DeepResearchError) as error: prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert error.value.code == 'shared_experiment_invocation_stopped' and invoke.call_count == 1


@pytest.mark.parametrize('mutation', ['response', 'binding', 'context', 'approval_type'])
def test_saved_state_tampering_does_not_send_again(mutation):
    r, data, aliases = context(); current, _, checkpoint = harness(r); invoke = Mock(return_value=response())
    prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    saved = current['state']['sharedExperimentGeneration']
    if mutation == 'response': saved['response']['content'] = '{}'
    elif mutation == 'binding': saved['boundProposal']['proposal']['budgets'][1]['cap'] = 99
    elif mutation == 'context': saved['contextDigest'] = digest('changed')
    else: saved['scientificApproval'] = 0
    with pytest.raises(DeepResearchError): prepare(current, data, aliases, invoke=invoke, checkpoint=checkpoint)
    assert invoke.call_count == 1


def test_default_facade_freezes_zero_even_if_client_requests_enablement(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo = DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **kwargs: None, llm_client=object())
    try:
        r, _ = facade.create({'workspaceTaskId':'t', 'operationKey':'op', 'question':'Design an experiment', MARKER:1}, start_async=False)
        assert r[MARKER] == 0 and not enabled(r)
        for v in (1, True, None):
            with pytest.raises(ValueError, match='Immutable'):
                repo.update_run(r['runId'], lambda r: {**r, MARKER:v})
    finally: facade.shutdown()


@pytest.mark.parametrize('provider_result', ['success', 'timeout', 'checkpoint_crash'])
def test_actual_tracked_scoped_http_schema_and_receipt_reuse(tmp_path, monkeypatch, provider_result):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.runtime import ScopedModelClient, research_model_options
    from services.deep_research.planning_transport import overhead_bytes
    from llm.client import DeepSeekLLM, LLMProviderError
    import requests
    from test_deep_research_schema_transport import response as http_response
    repo = DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    r, data, aliases = context(); repo.create_run(r); repo.begin_execution('r')
    post = (Mock(side_effect=requests.Timeout('fixture timeout')) if provider_result == 'timeout'
            else Mock(return_value=http_response(json.dumps(proposal()))))
    monkeypatch.setattr('llm.client.requests.post', post)
    provider = DeepSeekLLM(api_key='fixture', base_url='https://fixture.invalid')
    scoped = ScopedModelClient(repo, lambda *args: True, lambda: provider).for_run('r')
    reserve = Mock(wraps=repo.reserve_call)
    invoke = TrackedLLMInvoker(scoped, reserve, repo.complete_call, request_options=research_model_options,
                               run_record_fn=repo.require_run, experiment_max_input_bytes=32000)
    crash = [provider_result == 'checkpoint_crash']
    def checkpoint(v):
        if v['status'] == 'response_received' and crash[0]:
            crash[0] = False
            raise RuntimeError('Simulated crash after settled response, before proposal checkpoint')
        repo.update_run('r', lambda r:{**r, 'state':{**r['state'], 'sharedExperimentGeneration':deepcopy(v)}})
    def run():
        return prepare(repo.require_run('r'), data, aliases,
            invoke=lambda node,prompt,opts:invoke('r',node,prompt,opts,use_reserve=True), checkpoint=checkpoint)
    if provider_result == 'timeout':
        with pytest.raises(LLMProviderError): run()
        assert repo.list_calls('r')[0]['status'] == 'unknown'
        with pytest.raises(DeepResearchError): run()
        assert post.call_count == 1 and len(repo.list_calls('r')) == 1
        return
    if provider_result == 'checkpoint_crash':
        with pytest.raises(RuntimeError): run()
        assert post.call_count == 1 and repo.list_calls('r')[0]['settled'] == 1
        assert repo.require_run('r')['state']['sharedExperimentGeneration']['status'] == 'pending'
    result = run()
    assert result['status'] == 'awaiting_scientific_review' and result['scientificApproval'] is False
    assert run() == result and post.call_count == 1
    assert repo.list_calls('r')[0]['argsDigest'] == digest(result['request'])
    wire = post.call_args.kwargs['json']
    assert post.call_args.args[0].endswith('/responses') and wire['text']['format'] == descriptor()
    assert wire['max_output_tokens'] == 6144 and wire['reasoning']['effort'] == 'none'
    assert reserve.call_args.kwargs['budget_delta']['tokens'] == result['inputBytes']+1024+6144
    assert invoke.prompt_byte_limit('r',NODE) == 32000
    reserve.reset_mock()
    overlarge = 'x' * (32001-overhead_bytes(repo.require_run('r'), NODE))
    with pytest.raises(ValueError, match='Prompt too large'):
        invoke('r', NODE, overlarge, {'max_tokens':6144, 'temperature':0.0, 'timeout_seconds':90}, use_reserve=True)
    reserve.assert_not_called()
    assert post.call_count == 1

