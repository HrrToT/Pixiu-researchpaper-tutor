"""Quantity spellings in reported facts cannot weaken the evidence gate."""
import pytest

from services.deep_research.verification import make_evidence, precheck_claims, verify_claims


def check(quote, text, semantic=True):
    evidence = make_evidence(
        {'workId': 'paper', 'versionId': 'v1', 'contentHash': 'hash', 'accessLevel': 'fulltext'},
        quote, quote, location={'page': 5}, obligation_ids=['o1'])
    claim = {'claimId': 'c1', 'kind': 'reported', 'text': text,
             'evidenceRefs': [evidence['evidenceId']]}
    verdict = lambda claims, _: [{'claimId': c['claimId'], 'status': 'passed'} for c in claims]
    return verify_claims([claim], [evidence], verdict if semantic else None), evidence


@pytest.mark.parametrize(('quote', 'text', 'wrong_text'), [
    ('Evaluation on Mip-NeRF360 showed comparable metrics with 3D-GS.',
     '在 Mip-NeRF 360 数据集上，作者报告相近的画质指标。',
     '在 Mip-NeRF 360 数据集上，模型达到 360 FPS。'),
    ('We restricted Ficus to 5k Gaussians in both configurations.',
     'Ficus 的两种配置均限制高斯数量。', 'Ficus 的三种配置均限制高斯数量。'),
    ('Quantitative evaluation of our method, computed over three datasets.',
     '这张表汇总了三个数据集的结果。', '这张表汇总了四个数据集的结果。'),
])
def test_comparison_numeric_precheck_recognizes_cited_evaluation_labels_and_counts(quote, text, wrong_text):
    _, evidence = check(quote, text)
    claim = {'claimId': 'c1', 'kind': 'reported', 'text': text,
             'evidenceRefs': [evidence['evidenceId']]}
    assert precheck_claims([claim], [evidence], quantity_spelling_version=22)['rejected']
    assert precheck_claims([claim], [evidence], quantity_spelling_version=23)['candidates'] == [claim]
    modified = {**claim, 'text': wrong_text}
    assert precheck_claims([modified], [evidence],
                           quantity_spelling_version=23)['rejected'][0]['reason'] == 'numeric_mismatch'
    assert not verify_claims([claim], [evidence], quantity_spelling_version=23)['accepted']


@pytest.mark.parametrize(('quote', 'text'), [
    ('LPIPS is introduced after 150,000 steps.', '15万步后加入LPIPS损失'),
    ('LPIPS is introduced after 150000 steps.', '15 万步后加入LPIPS损失'),
    ('We train for 1.5e5 steps.', '训练150,000步'),
    ('We train for 150000.000 steps.', '训练15万步'),
    ('The model contains 1,500,000 points.', '模型包含150万个点'),
    ('The population is 200000000.', '数量为2亿'),
    ('The value is -1.5e-3.', '数值为-0.001500'),
    ('The value is +200.0.', '数值为200'),
    ('The factor is 15x.', '倍率为15倍'),
    ('The factor is 15×.', '倍率为15x'),
    ('The ratio is 66%.', '比例为66.0％'),
    ('The value is 1e100000.', '数值为10e99999'),
    ('The value is 123456789012345678901234567890.', '数值为12345678901234567890123456789e1'),
])
def test_exact_equivalent_quantities_are_candidates_for_semantic_check(quote, text):
    result, evidence = check(quote, text)
    assert result['accepted'] and not result['rejected']
    assert evidence['quote'] == quote and evidence['sourceContext'] == quote
    assert not check(quote, text, semantic=False)[0]['accepted']


@pytest.mark.parametrize(('quote', 'text'), [
    ('LPIPS is introduced after 150,000 steps.', '1.5万步后加入LPIPS损失'),
    ('LPIPS is introduced after 150,000 steps.', '15亿步后加入LPIPS损失'),
    ('LPIPS is introduced after 150,000 steps.', '150步后加入LPIPS损失'),
    ('LPIPS is introduced after 150,000 steps.', '0步后加入LPIPS损失'),
    ('The value is -1.5e-3.', '数值为0.0015'),
    ('The ratio is 66%.', '比例为66'),
    ('The ratio is 66%.', '倍率为66x'),
    ('The factor is 15x.', '数值为15'),
    ('The ratio is 0.66.', '比例为66%'),
    ('The value is 1.50,000.', '数值为150000'),
    ('The value is 1.50,000.', '数值为1.5'),
    ('The value is 1,50,000.', '数值为150000'),
    ('The value is 1,50,000.', '数值为50'),
    ('The value is 1,50,000.', '数值为0'),
    ('The value is 0.12345678901234567890123456789.', '数值为0.12345678901234567890123456788'),
    ('The value is 1e100000000000000000000.', '数值为1'),
    ('数量为15万分之一', '数量为150000'),
])
def test_wrong_values_or_dimensions_cannot_be_approved_by_model(quote, text):
    result, _ = check(quote, text)
    assert not result['accepted']
    assert result['rejected'][0]['reason'] == 'numeric_mismatch'


def test_saved_training_claim_can_reach_semantic_check_without_source_rewriting():
    # Mirrors the real H3R failure's quantities without changing its receipt.
    quote = 'We take 3 samples per ray. LPIPS is introduced after 150,000 steps; total training is 300,000 steps.'
    result, evidence = check(quote, '每条射线采样3次，15万步后加入LPIPS损失')
    assert result['accepted'] and evidence['quote'] == quote


@pytest.mark.parametrize(('quote', 'text', 'candidate'), [
    ('We start at 4 times smaller image resolution and upsample twice after 250 and 500 iterations.',
     '从4倍小的图像分辨率开始，并在250和500次迭代后各上采样一次。', True),
    ('We start at 4 times smaller image resolution and upsample twice after 250 and 500 iterations.',
     '从5倍小的图像分辨率开始，并在250和500次迭代后各上采样一次。', False),
    ('We start at 4 times smaller image resolution and upsample twice after 250 and 500 iterations.',
     '从4倍小的图像分辨率开始，并在250和600次迭代后各上采样一次。', False),
    ('We ran this 4 times and started at a smaller image resolution.',
     '从4倍小的图像分辨率开始。', False),
    ('We start at 4 times smaller image resolution and may upsample after 250 and 500 iterations.',
     '从4倍小的图像分辨率开始，并在250和500次迭代后各上采样一次。', False),
])
def test_saved_resolution_warmup_translation_keeps_exact_checked_quantities(quote, text, candidate):
    ev = make_evidence({'workId': 'paper', 'versionId': 'v1', 'contentHash': 'hash',
                        'accessLevel': 'fulltext'}, quote, quote, location={'page': 5}, obligation_ids=[])
    claim = {'claimId': 'c1', 'kind': 'reported', 'text': text, 'evidenceRefs': [ev['evidenceId']]}
    assert precheck_claims([claim], [ev], quantity_spelling_version=15)['rejected'][0]['reason'] == 'numeric_mismatch'
    result = precheck_claims([claim], [ev], quantity_spelling_version=16)
    assert (not result['rejected']) is candidate
    if candidate:
        def reject(claims, evidence):
            assert claims[0]['text'] == text and evidence[0]['quote'] == quote
            return [{'claimId': 'c1', 'status': 'failed', 'reason': 'Semantic check remains required.'}]
        assert not verify_claims([claim], [ev], reject, quantity_spelling_version=16)['accepted']


def test_shared_scale_range_preserves_both_endpoints_and_requires_semantic_review():
    quote = 'The resulting representation contains 1-5 million Gaussians for the tested scenes.'
    evidence = make_evidence({'workId': 'paper', 'versionId': 'v1', 'contentHash': 'hash',
                              'accessLevel': 'fulltext'}, quote, quote, location={'page': 5}, obligation_ids=[])
    text = '测试场景的表示包含1–5百万个高斯。'
    claim = {'claimId': 'c1', 'kind': 'reported', 'text': text, 'evidenceRefs': [evidence['evidenceId']]}
    assert precheck_claims([claim], [evidence], quantity_spelling_version=16)['rejected']
    assert precheck_claims([claim], [evidence], quantity_spelling_version=17)['candidates'] == [claim]

    for bad_text in ('测试场景包含1–6百万个高斯。', '测试场景恰好包含1个高斯。'):
        modified = {**claim, 'text': bad_text}
        assert precheck_claims([modified], [evidence], quantity_spelling_version=17)['rejected'][0]['reason'] == 'numeric_mismatch'

    def reject(claims, evidence_rows):
        assert claims[0]['text'] == text and evidence_rows[0]['quote'] == quote
        return [{'claimId': 'c1', 'status': 'failed', 'reason': 'The source scope must still be checked.'}]

    assert not verify_claims([claim], [evidence], reject, quantity_spelling_version=17)['accepted']


@pytest.mark.parametrize('text', ['1 - 5 million', '-1–5 million', '1–5 million%', '1–5百万分之一'])
def test_shared_scale_normalization_leaves_ambiguous_arithmetic_and_units(text):
    from services.deep_research.measurement_numbers import normalize_explicit_quantity_phrases

    assert normalize_explicit_quantity_phrases(text, shared_range_scale=True) == text


@pytest.mark.parametrize(('text', 'candidate'), [
    ('用随机单应变换从一张图生成另一张图；将像素中心映射。', True),
    ('从一张图像构造另一张图片。', True),
    ('每次从一张图生成另一张图。', False),
    ('只从一张图生成另一张图。', False),
    ('从一张图生成另一张图，而非使用同一张图。', False),
    ('从两张图生成另一张图。', False),
    ('从1张图生成另一张图。', False),
    ('从一张图生成另一张图；共使用5张图像训练。', False),
    ('从一张图生成另一张图；只使用一张图训练。', False),
])
def test_image_pair_introduction_preserves_explicit_counts_and_review(text, candidate):
    quote = 'We obtain image-pair correspondences by applying a random homography to an image.'
    evidence = make_evidence({'workId': 'paper', 'versionId': 'v1', 'contentHash': 'hash',
                              'accessLevel': 'fulltext'}, quote, quote, location={'page': 4}, obligation_ids=[])
    claim = {'claimId': 'c1', 'kind': 'reported', 'text': text, 'evidenceRefs': [evidence['evidenceId']]}
    for version in (17, 18):
        assert precheck_claims([claim], [evidence], quantity_spelling_version=version)['rejected']
    result = precheck_claims([claim], [evidence], quantity_spelling_version=19)
    assert result['candidates'] == ([claim] if candidate else [])
    if not candidate:
        assert result['rejected'][0]['reason'] == 'numeric_mismatch'
        return

    def reject(claims, evidence_rows):
        assert claims[0]['text'] == text and evidence_rows[0]['quote'] == quote
        return [{'claimId': 'c1', 'status': 'failed', 'reason': 'The source scope must still be checked.'}]

    assert not verify_claims([claim], [evidence], reject, quantity_spelling_version=19)['accepted']
