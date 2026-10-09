"""Render evidence-selected numbers once, before publishing grounded claims."""
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from services.comparison_measurements import MENTION, _numeric, validate_numeric_comparison
from services.research_synthesis import validate_claim
from services.evidence_quantity_text import render_author_quantity

TOKEN = re.compile(r'⟦数值([1-9]|1[0-2])⟧')
FREE_NUMBER = re.compile(r'(?<![A-Za-z0-9])\d+(?:\.\d+)?(?![A-Za-z0-9])')
QUANTITY = re.compile(
    r'(?:(?:at least|at most|more than|less than|up to|over|about|approximately)\s+|(?:[<>]=?|[≥≤≈~])\s*)?'
    r'\d+(?:\.\d+)?(?:\s*(?:–|—|to|-)\s*\d+(?:\.\d+)?)?\s*'
    r'(?:%|％|FPS|frames?\s*(?:per second|/\s*s)|[KMG]i?B|dB|倍|p)(?![A-Za-z0-9])', re.I)
METRIC_SCALAR = re.compile(r'\b(?:PSNR|SSIM|LPIPS)\s+(?:(?:increase|decrease|loss|drop)\s+(?:of\s+)?(?:only\s+)?)?'
                           r'(?P<value>[≥≤<>]?[ ]*\d+(?:\.\d+)?)', re.I)
PARAMETER_ROLE = re.compile(r'percentile|quantile|threshold|learning rate|hyperparameter|'
                            r'normaliz|clipp|parameter|分位|阈值|学习率|超参数|归一化|裁剪', re.I)
EXPERIMENT_ROLE = re.compile(r'FPS|frames?\s*(?:per second|/\s*s)|PSNR|SSIM|LPIPS|'
                             r'speedup|compression ratio|model size|memory consumption|'
                             r'accuracy|precision|recall|BLEU|ROUGE|improv|reduced by|'
                             r'压缩率|压缩比|帧率|加速比|模型大小|准确率|提升|降低了', re.I)
METHOD_SCALAR = re.compile(r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?')
COMPARATIVE = re.compile(r'高于|低于|优于|快于|更快|更小|领先|\b(?:better|faster|smaller)\b', re.I)

NUMERIC_PROMPT = '''数字输出合同：不要同时在summary和结构字段重复填写数字。
summary中所有数值写成⟦数值1⟧等占位符，并添加numericBindings（最多12项），每项id为1到12的整数；每个id使用一次。
提交前逐条检查：本条summary的占位符与本条numericBindings的id必须一一对应，不能附加正文未使用的绑定；定性结论不附实验数字绑定。
没有数字时省略numericBindings。数字结论不要另加旧measurements。参数、作者主张和实验结果须分开：
1. kind=experiment：选择sourceId、row、group（0起）、metric（原样指标名）、baselineRow、dataset、hardware、baseline和conditionReferences（sourceId/quoteId）。引用完整结果行与基线行。仅限verifiedTable的已核对列。
   operation为value、difference（结果减基线）、ratio（结果除基线）或inverse_ratio（基线除结果）；推算结论kind=inference，decimals可选0到6。不要填写value，服务端计算、舍入并说明升降。
   服务端插入数据集、指标、数值及紧凑硬件/基线条件，summary只写解释，不重复这些条件或手写下降幅度。
2. kind=method_parameter：选择sourceId/quoteId、label（原文参数名）和literal（同一摘录中的完整数值及单位）。只用于有明确参数/归一化/分位等定义的数值，不用于FPS、存储或质量提升。
3. kind=author_report：结论kind=reported，选择sourceId/quoteId及literal（原文完整数值表达式，保留≥、范围、at least等限定与单位）。只展示作者报告，不据此比较高低；分辨率等限制也分别绑定。
   完整数值短语的指标、升降或上下界由服务端呈现，summary不要在占位符旁重复这些词，更不能填写相反方向。
literal必须原样来自本条references的同一摘录，不改写引用。方法参数和作者主张不能用于绕过实验比较条件。
数据集名称中的数字不是测量值；名称仍须出现在引用正文并由已核对表格的数据集名称确认。作者报告可以绑定一段完整连续的数字短语，例如from 782MB to 45MB；保留短语中的全部数量、单位和限定。
例：{"summary":"作者报告实时渲染为⟦数值1⟧。","kind":"reported","numericBindings":[{"id":1,"kind":"author_report","sourceId":"来源ID","quoteId":"摘录ID","literal":"≥30fps"}],"references":[{"sourceId":"来源ID","quoteId":"摘录ID"}]}。
'''


def _mask_dataset_names(text, checked, sources):
    """Mask an identifier only when both cited prose and a same-paper table name agree."""
    refs = checked['references']
    paper_ids = {sources[ref['sourceId']]['pdfId'] for ref in refs}
    patterns = []
    for source in sources.values():
        if source['pdfId'] not in paper_ids:
            continue
        for name, _ in (source.get('_verifiedTable') or {}).get('groups', []):
            name = re.sub(r'\s+Datasets?$', '', name, flags=re.I)
            parts = re.findall(r'[A-Za-z]+|\d+', name)
            if not any(part.isdigit() for part in parts):
                continue
            pattern = re.compile(r'(?<![A-Za-z0-9])' + r'[\s-]*'.join(map(re.escape, parts))
                                 + r'(?:\s+Datasets?)?(?![A-Za-z0-9])', re.I)
            if any(ref['sourceId'] == source['sourceId'] or pattern.search(ref['quote']) for ref in refs
                   if sources[ref['sourceId']]['pdfId'] == source['pdfId']):
                patterns.append(pattern)
    for pattern in patterns:
        text = pattern.sub('数据集', text)
    return text


def _quantity_spans(text):
    spans = [(match.start(), match.end()) for match in QUANTITY.finditer(text)]
    spans.extend((match.start('value'), match.end('value')) for match in METRIC_SCALAR.finditer(text))
    return sorted(set(spans))


def _literal_ranges(literal, quote, checked, sources):
    """Accept contiguous short quantitative phrases, never cut a unit or comparator."""
    if not 1 <= len(literal) <= 200:
        return []
    spans = _quantity_spans(quote)
    accepted = []
    for match in re.finditer(re.escape(literal), quote):
        start, end = match.span()
        contained = [(a, b) for a, b in spans if start <= a and b <= end]
        if not contained or any(a < end and b > start and not (start <= a and b <= end) for a, b in spans):
            continue
        remainder = list(literal)
        for a, b in contained:
            remainder[a-start:b-start] = ' ' * (b-a)
        if FREE_NUMBER.search(_mask_dataset_names(''.join(remainder), checked, sources)):
            continue
        accepted.append((start, end))
    return accepted


def _supported_resolution(text, checked, sources):
    # A resolution repeated as prose is a condition, not a new performance value.
    # It must occur literally in a cited author report and next to resolution wording.
    supported = []
    for ref in checked['references']:
        for match in re.finditer(r'(?<![A-Za-z0-9.])\d{3,4}p(?![A-Za-z0-9])', ref['quote']):
            window = ref['quote'][max(0, match.start()-20):match.end()+20]
            if re.search(r'resolution|分辨率', window, re.I) and match.group() in text:
                supported.append((ref['sourceId'], ref['quote'], match.group()))
    for _, _, value in supported:
        text = re.sub(r'(?<![A-Za-z0-9.])' + re.escape(value) + r'(?![A-Za-z0-9])', '分辨率', text)
    return text, supported


def _required_report_spans(quote, covered):
    spans = _quantity_spans(quote)
    selected = {span for span in spans if any(a <= span[0] and span[1] <= b for a, b in covered)}
    required = set(selected)
    # Pair/range endpoints describe one quantitative relation. Other numbers in
    # the same excerpt may describe a different fact and need not be repeated.
    for left, right in zip(spans, spans[1:]):
        connector = quote[left[1]:right[0]].strip()
        if re.fullmatch(r'to|[-–—]', connector, re.I) and (left in selected or right in selected):
            required.update((left, right))
    if any(re.search(r'fps|frames?', quote[a:b], re.I) for a, b in selected):
        required.update((a, b) for a, b in spans
                        if re.fullmatch(r'\d{3,4}p', quote[a:b], re.I)
                        and re.search(r'resolution|分辨率', quote[max(0, a-20):b+20], re.I))
    return required


def _literal(binding, checked, sources):
    sid, quote, literal = binding.get('sourceId'), binding.get('quote'), binding.get('literal')
    source = sources.get(sid) if isinstance(sid, str) else None
    if not source or not isinstance(quote, str) or not isinstance(literal, str):
        raise ValueError('数值绑定缺少原文摘录。')
    if (source.get('metadata') or {}).get('evidence_kind') == 'table' or source.get('_verifiedTable'):
        raise ValueError('表格数字须使用实验绑定。')
    if not any(ref['sourceId'] == sid and ref['quote'] == quote for ref in checked['references']):
        raise ValueError('数值绑定不属于本条已引用摘录。')
    ranges = _literal_ranges(literal, quote, checked, sources)
    if binding['kind'] == 'method_parameter' and METHOD_SCALAR.fullmatch(literal):
        ranges.extend(match.span() for match in re.finditer(r'(?<![\w.+-])' + re.escape(literal) + r'(?!(?:\w|%|\.\d))', quote))
    if not ranges:
        raise ValueError('数值绑定改写或遗漏了原文数值、限定词或单位。')
    if binding['kind'] == 'method_parameter':
        label = binding.get('label')
        if not isinstance(label, str) or not 1 <= len(label) <= 80 or label not in quote:
            raise ValueError('方法参数没有原文名称。')
        if not any(PARAMETER_ROLE.search(quote[max(0, start - 80):end + 80])
                   for start, end in ranges) or EXPERIMENT_ROLE.search(quote):
            raise ValueError('方法参数不能替代实验指标依据。')
    return literal


def _experiment(binding, checked, sources):
    sid = binding.get('sourceId')
    packet = (sources.get(sid) or {}).get('_verifiedTable') if isinstance(sid, str) else None
    if not packet or 'value' in binding:
        raise ValueError('实验绑定须选择已核对表格，不重复填写value。')
    group, row_id, baseline_id = binding.get('group'), binding.get('row'), binding.get('baselineRow')
    if any(type(value) is not int for value in (group, row_id, baseline_id)) or not 0 <= group < len(packet['groups']):
        raise ValueError('实验绑定行列无效。')
    dataset, metrics = packet['groups'][group]
    metric = binding.get('metric')
    row = next((item for item in packet['rows'] if item[0] == row_id), None)
    baseline = next((item for item in packet['rows'] if item[0] == baseline_id), None)
    if row is None or baseline is None or metric not in metrics:
        raise ValueError('实验绑定结果、基线或指标未核对。')
    column = sum(len(item[1]) for item in packet['groups'][:group]) + metrics.index(metric)
    operation = binding.get('operation', 'value')
    decimals = binding.get('decimals')
    if (operation not in ('value', 'difference', 'ratio', 'inverse_ratio')
            or decimals is not None and (type(decimals) is not int or not 0 <= decimals <= 6)):
        raise ValueError('实验绑定运算或精度无效。')
    try:
        value, unit = _numeric(row[2][column])
        if operation != 'value':
            base, base_unit = _numeric(baseline[2][column])
            if base_unit != unit:
                raise ValueError('实验绑定的结果和基线量纲不一致。')
            if decimals is None:
                decimals = min(6, max(0, -value.as_tuple().exponent, -base.as_tuple().exponent)) if operation == 'difference' else 2
            value = value - base if operation == 'difference' else base / value if operation == 'inverse_ratio' else value / base
            # Do not round a genuine nonzero change to zero.
            rounded = value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
            if value != 0 and rounded == 0:
                raise ValueError('实验绑定精度会隐藏非零差异。')
            value = rounded
            if operation != 'difference':
                unit = ''
    except (InvalidOperation, ZeroDivisionError, IndexError) as error:
        raise ValueError('实验绑定计算无效。') from error
    number = format(value, 'f')
    measurement = {**binding, 'value': number + unit}
    canonical_unit = '倍' if operation in ('ratio', 'inverse_ratio') else unit or metric.upper()
    canonical = f"{dataset}（{binding.get('hardware')}，{baseline[1]}）：{number} {canonical_unit}"
    local = {**checked, 'summary': canonical, 'references': list(checked['references'])}
    validate_numeric_comparison({'kind': checked['kind'], 'measurements': [measurement]}, local, sources)
    checked['references'] = local['references']
    display_unit = 'dB' if unit == 'DB' or not unit and metric.upper() == 'PSNR' else unit
    if operation == 'difference':
        delta = '上升' if value > 0 else '下降' if value < 0 else '变化'
        display = f"{metric}{delta}{format(abs(value), 'f')} {display_unit}".strip()
    elif operation in ('ratio', 'inverse_ratio'):
        display = f"{metric}{'压缩' if operation == 'inverse_ratio' else '为基线的'}{number}倍"
    else:
        display = f"{metric} {number} {display_unit}".strip()
    return f'{dataset}：{display}', (binding['hardware'], baseline[1])


def check_numeric_claim(raw, sources):
    """Legacy recorded payloads stay strict; new bindings never use free values."""
    by_id = {source['sourceId']: source for source in sources}
    checked = validate_claim(raw, sources)
    if 'numericBindings' not in raw:
        if '⟦数值' in checked['summary']:
            raise ValueError('数值占位符缺少绑定。')
        validate_numeric_comparison(raw, checked, by_id)
        return checked
    bindings = raw['numericBindings']
    if not isinstance(bindings, list) or not 1 <= len(bindings) <= 12 or 'measurements' in raw:
        raise ValueError('数值绑定格式无效或混用了两种数字合同。')
    template = checked['summary']
    ids = TOKEN.findall(template)
    if len(set(ids)) != len(ids) or len(ids) != len(bindings):
        raise ValueError('数值占位符缺失、重复或多余。')
    without_tokens = TOKEN.sub('', template)
    quantitative_text = _mask_dataset_names(without_tokens, checked, by_id)
    quantitative_text, resolution_conditions = _supported_resolution(quantitative_text, checked, by_id)
    if ('⟦数值' in quantitative_text or FREE_NUMBER.search(quantitative_text)
            or MENTION.search(quantitative_text) or QUANTITY.search(quantitative_text)):
        raise ValueError('数值正文包含未绑定数字。')
    rendered, conditions, kinds, experiment_contexts = {}, [], set(), []
    for binding in bindings:
        if not isinstance(binding, dict) or type(binding.get('id')) is not int or str(binding['id']) not in ids:
            raise ValueError('数值绑定身份无效。')
        key, kind = str(binding['id']), binding.get('kind')
        if key in rendered or kind not in ('experiment', 'method_parameter', 'author_report'):
            raise ValueError('数值绑定身份重复或类别无效。')
        kinds.add(kind)
        if kind == 'experiment':
            rendered[key], condition = _experiment(binding, checked, by_id)
            dataset = by_id[binding['sourceId']]['_verifiedTable']['groups'][binding['group']][0]
            experiment_contexts.append((key, dataset, (binding['sourceId'], binding['group'],
                                       binding['row'], binding['baselineRow'], *condition)))
            if condition not in conditions:
                conditions.append(condition)
        else:
            rendered[key] = _literal(binding, checked, by_id)
            if kind == 'author_report':
                template, rendered[key] = render_author_quantity(template, key, rendered[key])
    if 'author_report' in kinds and (checked['kind'] != 'reported' or 'experiment' in kinds or COMPARATIVE.search(without_tokens)):
        raise ValueError('作者主张不能作为同条件实验比较。')
    if 'author_report' in kinds:
        # Preserve related endpoints and FPS resolution without forcing every
        # independent statistic in a paragraph into each single claim.
        reports = [binding for binding in bindings if binding['kind'] == 'author_report']
        for binding in reports:
            covered = [span for item in reports
                       if item['sourceId'] == binding['sourceId'] and item['quote'] == binding['quote']
                       for span in _literal_ranges(item['literal'], item['quote'], checked, by_id)]
            covered.extend(match.span() for sid, quote, value in resolution_conditions
                           if sid == binding['sourceId'] and quote == binding['quote']
                           for match in re.finditer(re.escape(value), quote))
            if any(not any(start <= a and b <= end for start, end in covered)
                   for a, b in _required_report_spans(binding['quote'], covered)):
                raise ValueError('作者报告遗漏了同段的数值范围或条件。')
    # The server supplies units. Remove only an immediately repeated same unit,
    # rather than asking the model to duplicate numeric presentation correctly.
    def insert(match):
        value = rendered[match[1]]
        return value
    for key, value in rendered.items():
        unit = re.search(r'(倍|FPS|[KMG]i?B|dB)$', value)
        if unit:
            template = re.sub(r'(⟦数值' + key + r'⟧)\s*' + re.escape(unit[1]), r'\1', template)
    # Share a dataset label only when EVERY binding describes the exact same
    # experiment. Mixed datasets, source tables, rows or conditions stay local.
    shared_dataset = None
    if (len(experiment_contexts) > 1 and len(experiment_contexts) == len(bindings)
            and len({context for _, _, context in experiment_contexts}) == 1):
        shared_dataset = experiment_contexts[0][1]
        for key, dataset, _ in experiment_contexts:
            rendered[key] = rendered[key][len(dataset) + 1:]
    checked['summary'] = TOKEN.sub(insert, template)
    if shared_dataset:
        checked['summary'] = f'{shared_dataset}：' + checked['summary']
    if conditions:
        checked['summary'] += '（' + '；'.join(f'{hardware}，基线{baseline}' for hardware, baseline in conditions) + '）'
    if 'author_report' in kinds:
        checked['summary'] += '（作者报告，未作同条件比较）'
    return checked
