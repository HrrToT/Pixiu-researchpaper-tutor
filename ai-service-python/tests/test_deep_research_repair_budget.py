import pytest
from services.deep_research.repair_budget import repair_prompt_byte_limit, REPAIR_OUTPUT_TOKENS
from services.deep_research.runtime import research_model_options


def test_observed_remaining_normal_pool_fits_without_raising_any_limit():
    budget = {'maxTokens': 100000, 'reserveTokens': 50000, 'tokens': 63217, 'normalTokens': 20707}
    assert repair_prompt_byte_limit(budget) == 20077
    assert budget['maxTokens'] == 100000


def test_total_pool_can_be_tighter_than_normal_pool():
    assert repair_prompt_byte_limit({'maxTokens': 100000, 'reserveTokens': 50000,
                                    'tokens': 90000, 'normalTokens': 100}) == 784


@pytest.mark.parametrize('used', [50000, 60000, True, -1, '100'])
def test_exhausted_or_invalid_capacity_never_creates_allowance(used):
    assert repair_prompt_byte_limit({'maxTokens': 100000, 'reserveTokens': 50000,
                                    'tokens': 1000, 'normalTokens': used}) == 0


def test_runtime_output_cap_matches_budget_planning():
    assert research_model_options('repair_claims', {})['max_tokens'] == REPAIR_OUTPUT_TOKENS
    assert repair_prompt_byte_limit({}) == 24000
    assert repair_prompt_byte_limit({'maxTokens': 100000}) == 24000


def test_observed_third_batch_can_allocate_smaller_output_without_borrowing_reserve():
    from services.deep_research.repair_budget import repair_batch_output_limit
    budget = {'maxTokens': 100000, 'reserveTokens': 50000, 'tokens': 42915, 'normalTokens': 20027}
    output = repair_batch_output_limit(5)
    assert output == 6144
    cap = repair_prompt_byte_limit(budget, output)
    assert cap == 22805 and 21653 <= cap
    options = research_model_options('repair_claims', {'_repair_output_limit': output})
    assert options['max_tokens'] == output and '_repair_output_limit' not in options
    assert budget['normalTokens'] + cap + output + 1024 == 50000


@pytest.mark.parametrize('value', [True, 0, -1, 8193, '4096'])
def test_invalid_server_output_allocation_is_rejected_before_provider(value):
    assert repair_prompt_byte_limit({}, value) == 0
    with pytest.raises(ValueError):
        research_model_options('repair_claims', {'_repair_output_limit': value})


def test_plain_tracked_invoker_strips_server_metadata_and_reserves_actual_output_limit():
    from unittest.mock import Mock
    from llm.provider import LLMResult, LLMUsage
    from services.deep_research.tools import TrackedLLMInvoker
    provider = Mock()
    provider.invoke.return_value = LLMResult('fixture', 'fixture', '[]', LLMUsage(8, 2, 10), 'stop')
    reserve = Mock(return_value=({'callId': 'c', 'reservationToken': 't'}, False))
    tracked = TrackedLLMInvoker(provider, reserve, Mock())
    tracked('r', 'repair_claims', 'prompt', {'_repair_output_limit': 6144})
    assert provider.invoke.call_args.args[0].extra_body == {'max_tokens': 6144}
    assert reserve.call_args.kwargs['budget_delta']['tokens'] == len(b'prompt') + 1024 + 6144


def test_exploration_leaves_room_for_whole_repair_request():
    from services.deep_research.contracts import check_exploration_headroom
    from services.deep_research.repair_budget import repair_exploration_headroom
    headroom = repair_exploration_headroom(50000)
    assert headroom == 33216
    budget = {'maxTokens': 100000, 'reserveTokens': 50000,
              'maxModelCalls': 18, 'reserveModelCalls': 5,
              'modelCalls': 5, 'normalTokens': 50000 - headroom}
    assert check_exploration_headroom(budget, 'extract') is None
    assert repair_prompt_byte_limit({**budget, 'tokens': budget['normalTokens']}) == 24000
    exhausted = {**budget, 'normalTokens': budget['normalTokens'] + 1}
    assert check_exploration_headroom(exhausted, 'extract')[0] == 'explorationTokens'
    assert check_exploration_headroom(exhausted, 'repair_claims') is None


def test_small_pool_keeps_exploration_and_final_pool_still_bounds_repair():
    from services.deep_research.repair_budget import repair_exploration_headroom
    assert repair_exploration_headroom(9000) == 6000
    # Protecting normal capacity never authorizes exceeding the overall pool.
    assert repair_prompt_byte_limit({'maxTokens': 100000, 'reserveTokens': 50000,
                                    'normalTokens': 10000, 'tokens': 99000}) == 0
