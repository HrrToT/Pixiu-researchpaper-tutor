"""Plain-language reading of one already bound, matched table pair."""

from decimal import Decimal
import re


_MEASUREMENT = re.compile(r'([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*([A-Za-z]*)')
_QUALITY_METRICS = ('psnr', 'ssim', 'lpips')
_METRICS = frozenset(('fps', 'size', *_QUALITY_METRICS))
_BYTE_UNITS = frozenset({'b', 'kb', 'kib', 'mb', 'mib', 'gb', 'gib', 'tb', 'tib'})
INTRO_PREFIX = '在这组同口径测试中，相比重新训练的基线，'


def summarize(selected, baseline_row):
    measurements = {True: {}, False: {}}
    for cell in selected:
        binding = cell['binding']
        metric = binding['metric'].strip().lower()
        if metric not in _METRICS:
            continue
        match = _MEASUREMENT.fullmatch(binding['value'].strip())
        if not match or len(match[1]) > 24:
            continue
        group = measurements[binding['rowNumber'] == baseline_row]
        if metric in group:
            return ''
        group[metric] = (Decimal(match[1]), match[2].lower())
    baseline, comparison = measurements[True], measurements[False]

    def difference(metric):
        if metric not in baseline or metric not in comparison:
            return None
        base_value, base_unit = baseline[metric]
        value, unit = comparison[metric]
        if unit != base_unit or (unit not in _BYTE_UNITS if metric == 'size' else bool(unit)):
            return None
        return (value > base_value) - (value < base_value)

    fps, size = difference('fps'), difference('size')
    quality = {metric: delta for metric in _QUALITY_METRICS if (delta := difference(metric)) is not None}
    if fps is None or size is None or not quality:
        return ''
    direction = {-1: '更低', 0: '相同', 1: '更高'}
    size_direction = {-1: '更小', 0: '相同', 1: '更大'}
    tradeoffs = '、'.join(metric.upper() + direction[delta] for metric, delta in quality.items())
    return (f'{INTRO_PREFIX}对照方法的帧率（FPS）{direction[fps]}，'
            f'体积指标（Size）{size_direction[size]}。画质指标中，{tradeoffs}。')
