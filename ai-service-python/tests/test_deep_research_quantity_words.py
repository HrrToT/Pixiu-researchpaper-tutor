from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.facade import ResearchFacade
from services.deep_research.measurement_numbers import measurement_numbers, number_display
from services.deep_research.repair import repair_rejected
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.verification import make_evidence, verify_claims


QUOTE = ('This maps the hash encoding to a 7-dimensional output: the first three dimensions indicate translation; '
         'the remaining dimensions represent rotation using quaternions.')


def setup(text, quote=QUOTE):
    ev = make_evidence({'workId': 'p', 'versionId': 'v', 'contentHash': 'h', 'accessLevel': 'fulltext'},
                      quote, quote, location={'page': 1}, obligation_ids=['o'])
    claim = {'claimId': 'c', 'text': text, 'kind': 'reported', 'evidenceRefs': [ev['evidenceId']],
             'conditions': {}, 'detailLevel': 'fulltext'}
    return claim, ev


@pytest.mark.parametrize('text,value', [
    ('the first three dimensions', '3e0'), ('Seven-dimensional output', '7e0'),
    ('two-stage pipeline', '2e0'), ('twelve samples', '12e0'), ('ten components', '1e1'),
    ('negative three components', '-3e0'), ('minus two channels', '-2e0'),
    ('前三个分量', '3e0'), ('后四个数', '4e0'), ('输出七维向量', '7e0'),
    ('共十组', '1e1'), ('十二个样本', '12e0'), ('负三维向量', '-3e0'),
])
def test_direct_small_count_spellings_are_exact_candidates(text, value):
    assert measurement_numbers(text, word_counts=True) == {value}


@pytest.mark.parametrize('text', ['twenty-three dimensions', 'fourteen components', 'one of the methods',
    'remaining dimensions', '二十三个分量', '一百零三个样本', '三点五次', '第一组', '第十二项'])
def test_unsupported_compounds_ordinals_and_implicit_counts_do_not_invent_small_numbers(text):
    assert measurement_numbers(text, word_counts=True) == set()


def test_legacy_parser_and_quotes_do_not_change():
    assert measurement_numbers(QUOTE) == {'7e0'}
    assert measurement_numbers(QUOTE, word_counts=True) == {'3e0', '7e0'}
    c, ev = setup('前3个输出表示平移。')
    original = deepcopy([c, ev])
    legacy = verify_claims([c], [ev])
    assert legacy['rejected'] == [{'claimId': 'c', 'reason': 'numeric_mismatch'}]
    check = Mock(return_value=[{'claimId': 'c', 'status': 'passed'}])
    assert verify_claims([c], [ev], check, quantity_spelling_version=1)['accepted']
    check.assert_called_once()
    assert [c, ev] == original
    assert not verify_claims([c], [ev], quantity_spelling_version=1)['accepted']


@pytest.mark.parametrize('text', ['输出7个数字，前3个表示平移，后4个表示旋转。',
    '输出七个数字，前三个表示平移，后四个表示旋转。'])
def test_remaining_dimension_arithmetic_is_not_promoted_to_reported_fact(text):
    c, ev = setup(text); check = Mock()
    result = verify_claims([c], [ev], check, quantity_spelling_version=1)
    rejection = result['rejected'][0]
    assert rejection['reason'] == 'numeric_mismatch'
    assert rejection['missingReportedNumbers'] == ['4e0']
    assert '4' in rejection['detail'] and '改kind' in rejection['detail']
    check.assert_not_called()


def test_wrong_signed_counts_and_percent_units_still_fail_before_semantics():
    for quote, text in [('negative three components', '3个分量'), ('three components', '3%'),
                        ('four components', '3个分量')]:
        c, ev = setup(text, quote); check = Mock()
        assert verify_claims([c], [ev], check, quantity_spelling_version=1)['rejected'][0]['reason'] == 'numeric_mismatch'
        check.assert_not_called()


def test_numerical_repair_receives_the_exact_missing_value_and_retains_qualitative_answer():
    c, ev = setup('输出7个数字，前3个表示平移，后4个表示旋转。')
    rejected = verify_claims([c], [ev], quantity_spelling_version=1)
    prompts = []
    def invoke(prompt):
        prompts.append(prompt)
        assert 'missingReportedNumbers' in prompt and '4e0' in prompt
        assert '本条引用原文未直接报告这些数值：4' in prompt
        return {'content': json.dumps([{'claimId': 'c', 'kind': 'reported',
            'text': '该网络预测位置平移和旋转。', 'evidenceRefs': ['E1'], 'conditions': {}, 'detailLevel': 'fulltext'}])}
    revised = repair_rejected({'claims': [c]}, rejected, [ev], '解释预测的变化', invoke, json.loads)
    assert len(prompts) == 1 and revised[0]['kind'] == 'reported'
    assert revised[0]['evidenceRefs'] == c['evidenceRefs']
    check = Mock(return_value=[{'claimId': 'c', 'status': 'passed'}])
    assert verify_claims(revised, [ev], check, quantity_spelling_version=1)['accepted']
    check.assert_called_once()


def test_readable_rejection_details_do_not_round_convert_or_expand_large_values():
    assert number_display('4e0') == '4'
    assert number_display('66e0%') == '66%'
    assert number_display('15e0x') == '15x'
    assert number_display('1e100000000') == '1e100000000'
    assert number_display('literal:bad') == 'literal:bad'


@pytest.mark.parametrize('replacement', [None, True, '3', 0, 1, 2, 9])
def test_spelling_policy_is_server_owned_frozen_and_used_by_facade(tmp_path, replacement):
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        run, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'o', 'question': '解释三个分量',
            'deferStart': True, 'quantitySpellingContractVersion': replacement}, start_async=False)
        assert run['quantitySpellingContractVersion'] == 8
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(run['runId'], lambda r: {**r, 'quantitySpellingContractVersion': replacement})
        c, ev = setup('前3个输出表示平移。')
        check = Mock(return_value=[{'claimId': 'c', 'status': 'passed'}])
        assert facade._get_verify_claims(run['runId'])([c], [ev], check)['accepted']
        repo.create_run({'runId': 'old', 'taskId': 't'})
        assert facade._get_verify_claims('old')([c], [ev], check)['rejected'][0]['reason'] == 'numeric_mismatch'
    finally: facade.shutdown()
