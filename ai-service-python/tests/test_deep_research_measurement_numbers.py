"""Quantity spellings in reported facts cannot weaken the evidence gate."""
import pytest

from services.deep_research.verification import make_evidence, verify_claims


def check(quote, text, semantic=True):
    evidence = make_evidence(
        {'workId': 'paper', 'versionId': 'v1', 'contentHash': 'hash', 'accessLevel': 'fulltext'},
        quote, quote, location={'page': 5}, obligation_ids=['o1'])
    claim = {'claimId': 'c1', 'kind': 'reported', 'text': text,
             'evidenceRefs': [evidence['evidenceId']]}
    verdict = lambda claims, _: [{'claimId': c['claimId'], 'status': 'passed'} for c in claims]
    return verify_claims([claim], [evidence], verdict if semantic else None), evidence


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
