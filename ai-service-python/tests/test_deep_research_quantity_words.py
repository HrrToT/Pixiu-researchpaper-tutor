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


@pytest.mark.parametrize('quote,claim_text,supported', [
    ('We evaluate at a480×640 resolution.', '图像分辨率为480×640。', True),
    ('We use inputs sized 480× 640.', '图像尺寸为480x640。', True),
    ('The frame size is 480x640px.', '图像尺寸为480×640像素。', True),
    ('The crop size is 256 x 256.', '裁剪为256×256。', True),
    ('The image was resized to 480x640.', '图像尺寸为480×640。', True),
    ('We evaluate at a480×640 resolution.', '图像分辨率为640×480。', False),
    ('We evaluate at a480×640 resolution.', '图像分辨率为480×641。', False),
    ('The sizes are 480 × 320 and 800 × 640.', '图像分辨率为480×640。', False),
    ('The values are 480, 640.', '图像分辨率为480×640。', False),
    ('The product identifier is A480×640.', '图像分辨率为480×640。', False),
    ('The product identifier is A-480 × 640.', '图像分辨率为480×640。', False),
    ('The tensor is 2.5 × 480 × 640.', '图像分辨率为480×640。', False),
    ('The tensor is 3×480×640.', '图像分辨率为480×640。', False),
    ('We evaluate at a480×640 resolution.', '系统提升480倍。', False),
])
def test_reported_dimensions_keep_order_and_direct_evidence(quote, claim_text, supported):
    c, ev = setup(claim_text, quote)
    original = deepcopy(ev)
    check = Mock(return_value=[{'claimId': 'c', 'status': 'passed'}])
    result = verify_claims([c], [ev], check, quantity_spelling_version=20)
    assert bool(result['accepted']) is supported
    assert ev == original
    if supported:
        check.assert_called_once()
    else:
        check.assert_not_called()
        assert result['rejected'][0]['reason'] == 'numeric_mismatch'
        if '480×640' in claim_text:
            assert '480×640' in result['rejected'][0]['detail']


def test_attached_pdf_resolution_equivalence_is_versioned():
    c, ev = setup('图像分辨率为480×640。', 'We evaluate at a480×640 resolution.')
    assert verify_claims([c], [ev], quantity_spelling_version=19)['rejected'][0]['reason'] == 'numeric_mismatch'
    assert verify_claims([c], [ev], quantity_spelling_version=20)['rejected'][0]['reason'] == 'semantic_unresolved'


@pytest.mark.parametrize('description,supported', [
    ('A single forward pass produces the point locations.', True),
    ('In one forward pass the network produces the point locations.', True),
    ('A forward pass produces the point locations.', False),
    ('Multiple forward passes produce the point locations.', False),
    ('A single image supplies the point locations.', False),
])
def test_only_explicit_single_forward_pass_supports_cardinality(description, supported):
    c, ev = setup('一次前向传播生成关键点位置。', description)
    checker = Mock(return_value=[{'claimId': 'c', 'status': 'passed'}])
    result = verify_claims([c], [ev], checker, quantity_spelling_version=20)
    assert bool(result['accepted']) is supported


def test_bicubic_interpolation_name_is_not_a_count_of_operations():
    quote = 'We use bi-cubic interpolation followed by L2 normalization.'
    c, ev = setup('在检测位置用双三次插值，再做L2归一化。', quote)
    assert verify_claims([c], [ev], quantity_spelling_version=20)['rejected'][0]['missingReportedNumbers'] == ['3e0']
    checker = Mock(return_value=[{'claimId': 'c', 'status': 'passed'}])
    assert verify_claims([c], [ev], checker, quantity_spelling_version=21)['accepted']
    repeated, ev = setup('在检测位置重复三次双三次插值。', quote)
    result = verify_claims([repeated], [ev], quantity_spelling_version=21)
    assert result['rejected'][0]['missingReportedNumbers'] == ['3e0']


@pytest.mark.parametrize('quote,missing', [
    ('We introduce one band of the SH after every 1000 iterations until all 4 bands are represented.', []),
    ('We introduce SH bands after every 1000 iterations until all 4 bands are represented.', ['1e0']),
    ('One experiment introduces SH bands after every 1000 iterations until all 4 bands are represented.', ['1e0']),
    ('We introduce one band of the SH after every 2000 iterations until all 4 bands are represented.', ['1e3']),
])
def test_scheduled_sh_band_cardinality_stays_bound_to_explicit_source(quote, missing):
    c, ev = setup('每 1000 次迭代引入一个球谐频带，直至共 4 个频带。', quote)
    checker = Mock(return_value=[{'claimId': 'c', 'status': 'passed'}])
    result = verify_claims([c], [ev], checker, quantity_spelling_version=22)
    if missing:
        assert result['rejected'][0]['missingReportedNumbers'] == missing
    else:
        assert result['accepted']
        assert verify_claims([c], [ev], quantity_spelling_version=21)['rejected'][0]['missingReportedNumbers'] == ['1e0']


@pytest.mark.parametrize('replacement', [None, True, '3', 0, 1, 2, 8, 16])
def test_spelling_policy_is_server_owned_frozen_and_used_by_facade(tmp_path, replacement):
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        run, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'o', 'question': '解释三个分量',
            'deferStart': True, 'quantitySpellingContractVersion': replacement}, start_async=False)
        assert run['quantitySpellingContractVersion'] == 22
        changed = 15 if replacement == 16 else replacement
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(run['runId'], lambda r: {**r, 'quantitySpellingContractVersion': changed})
        c, ev = setup('前3个输出表示平移。')
        check = Mock(return_value=[{'claimId': 'c', 'status': 'passed'}])
        assert facade._get_verify_claims(run['runId'])([c], [ev], check)['accepted']
        repo.create_run({'runId': 'old', 'taskId': 't'})
        assert facade._get_verify_claims('old')([c], [ev], check)['rejected'][0]['reason'] == 'numeric_mismatch'
    finally: facade.shutdown()
