import pytest

from services.deep_research.benchmark_tradeoff_summary import summarize
from services.deep_research.comparison_presentation import sections, audit_digest


def selected(size='45MB'):
    return [{'binding': {'rowNumber': row, 'metric': metric, 'value': value}}
            for row, values in [(5, ['144', '782MB', '27.40', '0.813', '0.217']),
                                (6, ['237', size, '27.13', '0.806', '0.237'])]
            for metric, value in zip(('FPS', 'Size', 'PSNR', 'SSIM', 'LPIPS'), values, strict=True)]


def test_matched_summary_uses_directions_of_only_comparable_bound_cells():
    text = summarize(list(reversed(selected())), baseline_row=5)
    assert '帧率（FPS）更高，体积指标（Size）更小' in text
    assert 'PSNR更低、SSIM更低、LPIPS更高' in text
    assert 'PSNR更高' in summarize(selected(), baseline_row=6)
    assert '144' not in text and '显存' not in text


@pytest.mark.parametrize('size', ['45', '45MiB', '≤45MB'])
def test_ambiguous_or_different_size_units_do_not_generate_a_tradeoff_summary(size):
    assert summarize(selected(size), baseline_row=5) == ''


def test_metric_explanation_requires_and_follows_the_exact_bound_arrows():
    unmarked = selected()
    directions = {'PSNR': '↑', 'SSIM': '↑', 'LPIPS': '↓'}
    marked = [{'binding': {**cell['binding'],
                           'metric': cell['binding']['metric'] + directions.get(cell['binding']['metric'], '')}}
              for cell in unmarked]
    assert '越好' not in summarize(unmarked, baseline_row=5, explain_metrics=True)
    text = summarize(marked, baseline_row=5, explain_metrics=True)
    assert 'PSNR（峰值信噪比）越高越好' in text
    assert 'SSIM（结构相似度）越高越好' in text
    assert 'LPIPS（感知差异）越低越好' in text
    marked[-1]['binding']['metric'] = 'LPIPS↑'
    assert 'LPIPS（感知差异）' not in summarize(marked, baseline_row=5, explain_metrics=True)


def test_intro_order_is_bound_to_the_same_audit_as_the_accepted_comparison():
    claims = [{'claimId': 'boundary', 'kind': 'inference', 'text': 'Boundary.'},
              {'claimId': 'example', 'kind': 'reported', 'text': 'Matched comparison.'}]
    layout = {'version': 3, 'layout': [], 'sources': {}, 'jointGoals': []}
    lead = {**layout, 'beginnerLeadClaimId': 'example'}
    assert sections(layout, claims)[0]['claimIds'] == ['boundary', 'example']
    assert sections(lead, claims)[0]['claimIds'] == ['example', 'boundary']
    assert audit_digest(lead, claims) != audit_digest(layout, claims)
    assert sections(lead, claims[:1])[0]['claimIds'] == ['boundary']


@pytest.mark.parametrize('lpips,quality', [
    ('0.237', '但可比较的画质指标都较差'),
    ('0.217', '可比较的画质指标有下降'),
    ('0.201', '画质指标有改善也有下降'),
])
def test_plain_intro_explains_the_tradeoff_using_metric_direction(lpips, quality):
    cells = selected()
    arrows = {'PSNR': '↑', 'SSIM': '↑', 'LPIPS': '↓'}
    for cell in cells:
        binding = cell['binding']
        if binding['rowNumber'] == 6 and binding['metric'] == 'LPIPS':
            binding['value'] = lpips
        binding['metric'] += arrows.get(binding['metric'], '')
    before = summarize(cells, 5, explain_metrics=True)
    after = summarize(cells, 5, explain_metrics=True, plain_tradeoff=True)
    assert '模型体积更小，每秒能渲染更多帧' in after
    assert quality in after
    assert 'PSNR更低' in before and '按原表箭头' in after
    assert all(number not in after for number in ('782', '237', '45MB'))


def test_plain_intro_keeps_raw_metric_directions_when_preference_is_unknown():
    assert summarize(selected(), 5, plain_tradeoff=True) == summarize(selected(), 5)


def test_plain_intro_is_versioned_and_remains_specific_to_beginner_requests():
    from services.deep_research.comparison_joint_reports import scoped_example_presentation

    old = {'comparisonBenchmarkSpeedScopeContractVersion': 7, 'question': '向初学者比较论文'}
    assert scoped_example_presentation(old) == 4
    new = {**old, 'comparisonBeginnerLeadContractVersion': 1}
    assert scoped_example_presentation(new) == 5
    assert scoped_example_presentation({**new, 'question': '比较论文'}) == 2
