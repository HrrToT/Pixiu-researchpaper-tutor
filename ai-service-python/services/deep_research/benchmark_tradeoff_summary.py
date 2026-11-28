"""Plain-language reading of one already bound, matched table pair."""

from decimal import Decimal
import re


_MEASUREMENT = re.compile(r'([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*([A-Za-z]*)')
_QUALITY_METRICS = ('psnr', 'ssim', 'lpips')
_QUALITY_NAMES = {'psnr': '峰值信噪比', 'ssim': '结构相似度', 'lpips': '感知差异'}
_METRICS = frozenset(('fps', 'size', *_QUALITY_METRICS))
_BYTE_UNITS = frozenset({'b', 'kb', 'kib', 'mb', 'mib', 'gb', 'gib', 'tb', 'tib'})
INTRO_PREFIX = '在这组同口径测试中，相比重新训练的基线，'


def summarize(selected, baseline_row, *, explain_metrics=False, plain_tradeoff=False):
    measurements = {True: {}, False: {}}
    for cell in selected:
        binding = cell['binding']
        raw_metric = binding['metric'].strip().lower()
        arrow = raw_metric[-1] if raw_metric.endswith(('↑', '↓')) else ''
        metric = raw_metric.rstrip('↑↓').strip()
        if metric not in _METRICS:
            continue
        match = _MEASUREMENT.fullmatch(binding['value'].strip())
        if not match or len(match[1]) > 24:
            continue
        group = measurements[binding['rowNumber'] == baseline_row]
        if metric in group:
            return ''
        group[metric] = (Decimal(match[1]), match[2].lower(), arrow)
    baseline, comparison = measurements[True], measurements[False]

    def difference(metric):
        if metric not in baseline or metric not in comparison:
            return None
        base_value, base_unit, base_arrow = baseline[metric]
        value, unit, arrow = comparison[metric]
        if (arrow != base_arrow or unit != base_unit
                or (unit not in _BYTE_UNITS if metric == 'size' else bool(unit))):
            return None
        return (value > base_value) - (value < base_value)

    fps, size = difference('fps'), difference('size')
    quality = {metric: delta for metric in _QUALITY_METRICS if (delta := difference(metric)) is not None}
    if fps is None or size is None or not quality:
        return ''
    direction = {-1: '更低', 0: '相同', 1: '更高'}
    size_direction = {-1: '更小', 0: '相同', 1: '更大'}
    tradeoffs = '、'.join(metric.upper() + direction[delta] for metric, delta in quality.items())
    text = (f'{INTRO_PREFIX}对照方法的帧率（FPS）{direction[fps]}，'
            f'体积指标（Size）{size_direction[size]}。画质指标中，{tradeoffs}。')
    if plain_tradeoff:
        # Interpret quality only where the source specifies the preferred
        # direction. A lower error metric is not a drop in image quality.
        quality_changes = {delta if baseline[metric][2] == '↑' else -delta
                           for metric, delta in quality.items() if baseline[metric][2] in ('↑', '↓')}
        if all(baseline[metric][2] in ('↑', '↓') for metric in quality):
            if {1, -1} <= quality_changes:
                quality_text = '所列画质指标有改善也有下降'
            elif 1 in quality_changes:
                quality_text = '可比较的画质指标有改善'
            elif -1 in quality_changes:
                quality_text = '可比较的画质指标有下降' if 0 in quality_changes else '可比较的画质指标都较差'
            else:
                quality_text = '所列画质指标持平'
            frames = {-1: '每秒能渲染的帧数更少', 0: '每秒渲染的帧数相同', 1: '每秒能渲染更多帧'}
            transition = '，但' if (fps > 0 or size < 0) and quality_changes == {-1} else '，'
            text = f'{INTRO_PREFIX}对照方法的模型体积{size_direction[size]}，{frames[fps]}{transition}{quality_text}。'
    if explain_metrics:
        explained = [f"{metric.upper()}（{_QUALITY_NAMES[metric]}）越{'高' if arrow == '↑' else '低'}越好"
                     for metric in quality if (arrow := baseline[metric][2])]
        if explained:
            text += '按原表箭头，' + '，'.join(explained) + '。'
    return text
