from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.audience_responsibilities import manifest
from services.deep_research.audience_rewrite import _prepare, rewrite_for_beginner
from services.deep_research.contracts import DeepResearchError
from test_deep_research_audience_edit_budget import fixture, options, answer
from test_deep_research_audience_editable_source import read_sources


def inputs():
    report, ev, q = fixture()
    report['claims'][1]['obligationIds'] = ['limit']
    requirements = [{'obligationId': 'o', 'question': '解释操作怎样改变输出',
                     'completionCriteria': [{'criterionId': 'a', 'requirement': '解释操作', 'responseType': 'explanation'}]},
                    {'obligationId': 'limit', 'question': '说明证据能够支持的范围'}]
    opts = {**options(), 'editable_source_first': True,
            'scoped_editable_source': True, 'requirement_context': requirements}
    return report, ev, q, opts


def test_responsibility_map_preserves_assignments_and_distinguishes_exclusive_fixed_questions():
    report, _, _, opts = inputs(); before = deepcopy((report, opts))
    value = manifest(report, opts['requirement_context'], ['fixed'])
    assert value['fixedOnlyObligationIds'] == ['limit']
    assert value['editableTargets'] == [{'claimId': 'edit', 'obligationIds': ['o']}]
    assert value['requestedPoints'] == opts['requirement_context']
    assert (report, opts) == before
    report['claims'][0]['obligationIds'].append('limit')
    assert manifest(report, opts['requirement_context'], ['fixed'])['fixedOnlyObligationIds'] == []


def test_new_prompt_adds_responsibility_map_without_changing_own_sources_or_budget():
    report, ev, q, opts = inputs(); old_opts = {**opts, 'scoped_editable_source': False}
    old, reason = _prepare(report, ev, q, **old_opts); assert reason is None
    new, reason = _prepare(report, ev, q, **opts); assert reason is None
    marker = '\nReader responsibility map (UNVERIFIED draft assignments, not evidence of coverage):\n'
    assert new['prompt'].startswith(old['prompt'] + marker)
    assert read_sources(old['prompt']) == read_sources(new['prompt'])
    assert new['outputTokens'] == old['outputTokens'] == 3072
    assert len(new['prompt'].encode()) <= 24000
    assert report['claims'][0]['text'] not in new['prompt']
    assert 'A shared obligation is NOT fixed-only' in new['prompt']


@pytest.mark.parametrize('bad', ['unknown', 'duplicate_requirement', 'empty_assignment', 'duplicate_assignment'])
def test_ambiguous_assignment_skips_edit_without_unscoped_fallback(bad):
    report, ev, q, opts = inputs(); states = []; invoke = Mock()
    if bad == 'unknown': report['claims'][0]['obligationIds'] = ['foreign']
    elif bad == 'duplicate_requirement': opts['requirement_context'].append(deepcopy(opts['requirement_context'][0]))
    elif bad == 'empty_assignment': report['claims'][0]['obligationIds'] = []
    else: report['claims'][0]['obligationIds'] = ['o', 'o']
    result = rewrite_for_beginner(report, ev, q, invoke, json.loads, checkpoint=states.append, **opts)
    assert result == report and states[-1]['reason'] == 'invalid_point_responsibilities'
    invoke.assert_not_called()


def test_new_mode_reuses_received_reply_and_cannot_switch_saved_modes():
    report, ev, q, opts = inputs(); states = []; invoke = Mock(return_value=answer())
    result = rewrite_for_beginner(report, ev, q, invoke, json.loads, checkpoint=states.append, **opts)
    assert states[-1]['audienceEditableSourceContractVersion'] == 2
    assert result['claims'][1] == report['claims'][1]
    invoke.reset_mock()
    assert rewrite_for_beginner(report, ev, q, invoke, json.loads, saved_state=states[-1], **opts) == result
    invoke.assert_not_called()
    for mutation in ('mode', 'version', 'assignments'):
        saved = deepcopy(states[-1]); changed = deepcopy(opts)
        if mutation == 'mode': changed['scoped_editable_source'] = False
        elif mutation == 'version': saved['audienceEditableSourceContractVersion'] = 1
        else: changed['requirement_context'][0]['question'] = '另一个职责'
        with pytest.raises(DeepResearchError):
            rewrite_for_beginner(report, ev, q, invoke, json.loads, saved_state=saved, **changed)
    invoke.assert_not_called()


def test_unknown_transport_is_not_reinterpreted_as_a_bad_edit():
    report, ev, q, opts = inputs(); states = []
    error = DeepResearchError('external_call_unknown', 'Unknown original request')
    invoke = Mock(side_effect=error)
    with pytest.raises(DeepResearchError) as caught:
        rewrite_for_beginner(report, ev, q, invoke, json.loads, checkpoint=states.append, **opts)
    assert caught.value is error and states[-1]['status'] == 'pending'
    assert states[-1]['audienceEditableSourceContractVersion'] == 2
    invoke.assert_called_once()


def test_actual_unknown_ledger_blocks_same_scoped_request_reissue(tmp_path):
    from llm.provider import LLMProviderError
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.contracts import UnknownCallError
    report, ev, q, opts = inputs(); states = []; sends = []
    repo = DeepResearchRepository(str(tmp_path/'calls.sqlite3')); repo.initialize()
    repo.create_run({'runId': 'r'}); repo.begin_execution('r')
    class Provider:
        def invoke(self, request):
            sends.append(request.prompt)
            raise LLMProviderError('Unknown', provider='fixture', model='fixture')
    tracked = TrackedLLMInvoker(Provider(), repo.reserve_call, repo.complete_call)
    def invoke(prompt, output):
        return tracked('r', 'synthesize_audience', prompt, {'max_tokens': output})
    with pytest.raises(LLMProviderError):
        rewrite_for_beginner(report, ev, q, invoke, json.loads, checkpoint=states.append, **opts)
    with pytest.raises(UnknownCallError):
        rewrite_for_beginner(report, ev, q, invoke, json.loads, saved_state=states[-1], **opts)
    assert len(sends) == 1 and repo.list_calls('r')[0]['status'] == 'unknown'


@pytest.mark.parametrize('bad', [1, None, 'true'])
def test_scope_policy_is_typed(bad):
    report, ev, q, opts = inputs(); opts['scoped_editable_source'] = bad
    with pytest.raises(ValueError): _prepare(report, ev, q, **opts)
