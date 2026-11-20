"""Validate reported table measurements against exact cited cells."""
import re
from decimal import Decimal

from services.deep_research.table_evidence import visible_table_packet

_VALUE = r'\d+(?:\.\d+)?'
_METRIC = re.compile(rf'(?<![A-Za-z])(FPS|PSNR|SSIM|LPIPS|Size|Mem)\s*[↑↓:=：]?\s*({_VALUE})', re.I)
_UNIT = re.compile(rf'({_VALUE})\s*(FPS|[KMG]i?B|dB)(?![A-Za-z])', re.I)
_DURATION_LABELS = {
    'train': ('训练时间','训练耗时'), 'training': ('训练时间','训练耗时'),
    'traintime': ('训练时间','训练耗时'), 'trainingtime': ('训练时间','训练耗时'),
    'time': ('时间','耗时','时长'), 'duration': ('持续时间','时长'),
    'latency': ('延迟','时延'), 'runtime': ('运行时间','耗时'),
    'rendertime': ('渲染时间','渲染耗时'), 'renderingtime': ('渲染时间','渲染耗时'),
    'optimizationtime': ('优化时间','优化耗时'), 'optimisationtime': ('优化时间','优化耗时')}


def _duration_metric_key(metric):
    return re.sub(r'[^a-z]', '', re.sub(r'\([^)]*\)', '', metric).casefold())


def _key(text):
    return re.sub(r'\s+', '', text).casefold()


def dataset_label(text):
    """Drop only a generic trailing English descriptor, never a split/variant."""
    return re.sub(r'\s+datasets?\s*$', '', text, flags=re.I).strip() or text


def _method_visible(method, text):
    # A table's trailing bibliography number is not a method variant. Keep
    # stars, ablation suffixes and training variants as part of the identity.
    label = re.sub(r'\s*\[\d+(?:\s*[,\-–]\s*\d+)*\]\s*$', '', method)
    token = _key(label)
    # Keep spaces around the displayed label: removing them would turn
    # "Ours PSNR" into "OursPSNR" and wrongly reject a separate method name.
    pattern = r'\s*'.join(re.escape(char) for char in token)
    return bool(token and re.search(r'(?<![a-z0-9*+_.-])' + pattern
        + r'(?!\s*[*+_.-]|[a-z0-9])', text.casefold()))


def bound_table_context(claim, evidence):
    """Expose parser-established cell identities to a wording-only rewrite.

    This is a prompt aid, not a semantic approval or permission to change a
    binding. Only exact cells in this claim's own quotations are included.
    """
    cited = {e.get('evidenceId'): e for e in evidence
             if e.get('evidenceId') in claim.get('evidenceRefs', [])}
    bindings = claim.get('tableBindings')
    result = []
    for binding in bindings if isinstance(bindings, list) else []:
        if not isinstance(binding, dict) or not isinstance(binding.get('evidenceId'), str):
            continue
        source = cited.get(binding['evidenceId'], {})
        packet = visible_table_packet(source.get('tableData'), source.get('quote', ''))
        group, number = binding.get('groupIndex'), binding.get('rowNumber')
        if (not packet or type(group) is not int or type(number) is not int
                or not 0 <= group < len(packet['groups'])):
            continue
        dataset, metrics = packet['groups'][group]
        row = next((r for r in packet['rows'] if r[0] == number), None)
        metric = binding.get('metric')
        if row is None or metric not in metrics:
            continue
        column = sum(len(g[1]) for g in packet['groups'][:group]) + metrics.index(metric)
        value = row[2][column]
        if value != binding.get('value'):
            continue
        result.append({'group': dataset, 'method': row[1], 'metric': metric, 'value': value})
    return result


def normalize_bound_duration_spelling(text, claim, evidence):
    """Compare equivalent time spellings only for exact, valid own table cells.

    No unit arithmetic, rounding, source edits or public-text edits. A whole
    component sequence such as 41m33s may match 41分33秒; 2433秒 is a derived
    conversion and is deliberately not admitted here.
    """
    units = {'h':'h','hr':'h','hrs':'h','hour':'h','hours':'h','小时':'h',
             'm':'m','min':'m','mins':'m','minute':'m','minutes':'m','分':'m','分钟':'m',
             's':'s','sec':'s','secs':'s','second':'s','seconds':'s','秒':'s'}
    unit = '|'.join(re.escape(u) for u in sorted(units, key=len, reverse=True))
    token = re.compile(r'(\d+(?:\.\d+)?)\s*(' + unit + r')', re.I)
    duration = re.compile(r'(?<![A-Za-z0-9])(?:\d+(?:\.\d+)?\s*(?:' + unit
                          + r')\s*){1,3}(?![A-Za-z0-9])', re.I)
    def parts(value):
        matches = list(token.finditer(value.strip()))
        if not matches or token.sub('', value.strip()).strip():
            return None
        values = [(Decimal(m[1]), units[m[2].casefold()]) for m in matches]
        order = ['hms'.index(u) for _, u in values]
        return tuple(values) if order == sorted(set(order)) else None
    allowed = {}
    for cell in bound_table_context(claim, evidence):
        metric = re.sub(r'\([^)]*\)', '', cell['metric']).strip().casefold()
        if _duration_metric_key(metric) not in _DURATION_LABELS \
                and not any(u in metric for u in ('时间','耗时','时长')):
            continue
        components = parts(cell['value'])
        if components is not None:
            allowed[components] = cell['value']
    return duration.sub(lambda m: allowed.get(parts(m[0]), m[0]) +
                        (m[0][len(m[0].rstrip()):] if parts(m[0]) in allowed else ''), text)


def declared_references_enabled(record):
    return (type(record.get('tableReferencesContractVersion')) is int
            and record['tableReferencesContractVersion'] in (1,2,3,4))


REFERENCE_GUIDANCE=('For every tableBindings entry, rowNumber is the explicit source row ID '
    'in the supplied tableData/quotation, NOT a zero-based position among selected rows. '
    'Only groupIndex is zero-based. Copy exact source cells regardless of claim kind; '
    'derived values are reasoning, not invented source-cell references.')


def reference_guidance(version):
    if type(version) is not int or version != 4:
        return REFERENCE_GUIDANCE
    return ('For tableBindings, copy the explicit source rowNumber (not selected-row position); '
        'groupIndex is zero-based. metric is an EXACT member of tableData.groups[groupIndex][1], '
        'including when tableDataRef resolves that packet. A quotation can print PSNR↑ while '
        'the packet metric is PSNR: bind PSNR, not PSNR↑. Direction arrows remain in source '
        'prose and must inform interpretation; do not append, remove or reverse them in the '
        'declared packet key. If the actual packet key includes an arrow, copy it exactly. '
        'Without a visible packet/key do not guess a binding. Copy exact source values '
        'regardless of claim kind; derived quantities are reasoning, never source cells.')


def validate_declared_references(claim,evidence):
    """Validate declared source cells without misclassifying derived quantities."""
    if 'tableBindings' not in claim:
        return None
    bindings=claim['tableBindings']
    if not isinstance(bindings,list):
        return 'invalid_table_binding'
    for binding in bindings:
        target={'evidenceRefs':claim.get('evidenceRefs',[]),'tableBindings':[binding]}
        if len(bound_table_context(target,evidence))==1:
            continue
        # The existing validator diagnoses malformed/out-of-scope/unknown cells.
        # No generated prose is used as authority for the cell identity.
        reason=validate_table_bindings({**target,'text':'','conditions':{}},evidence)
        return reason or 'unverified_table_cell'
    return None


def available_reference_rows(claim,evidence):
    """Bounded parser-established identities, advisory repair metadata only."""
    refs=set(claim.get('evidenceRefs',[]));rows=[]
    for ev in evidence:
        if ev.get('evidenceId') not in refs:
            continue
        packet=visible_table_packet(ev.get('tableData'),ev.get('quote',''))
        if packet:
            rows.append({'evidenceId':ev['evidenceId'],
                'rows':[{'rowNumber':row[0],'method':row[1]} for row in packet['rows'][:12]],
                'groups':[{'groupIndex':i,'label':group[0],'metrics':group[1]}
                          for i,group in enumerate(packet['groups'])]})
        if len(rows)==8:
            break
    return rows


def _dataset_key(text, joiners):
    # Only typographic spelling of a conjunction between Latin name tokens.
    # Never remove a split, hierarchy level, number or method variant.
    if joiners:
        text = re.sub(r'(?<=[A-Za-z0-9])\s*&\s*(?=[A-Za-z0-9])', ' and ', text)
    return _key(text)


def validate_comparison_measurements(claim, evidence, **options):
    """Check factual metric operands embedded in ordinary comparison advice.

    Expand bounded display spellings in a validation-only view. No numeric
    conversion, table selection, rewritten claim or semantic approval occurs.
    """
    text = str(claim.get('text', ''))
    labels = r'(FPS|PSNR|SSIM|LPIPS|Size|Mem)'
    first = rf'(?<![A-Za-z]){labels}\s*(?:[↑↓:=：]|为|是|从|由|of|is|from)?\s*({_VALUE})'
    continuation = re.compile(rf'\s*(?:下降到|下降至|降低至|提高至|提升至|降至|升至|到|至|→|->|to|versus|vs\.?|and|与|和|、|/)\s*({_VALUE})', re.I)
    measurements = []
    for match in re.finditer(first, text, re.I):
        metric, value = match.groups()
        measurements.append(f'{metric} {value}')
        end = match.end()
        while (following := continuation.match(text, end)) is not None:
            measurements.append(f'{metric} {following.group(1)}')
            end = following.end()
    view = {**claim, 'text': text + ' ' + ' '.join(measurements)}
    return validate_table_bindings(view, evidence, **options)


def validate_table_bindings(claim, evidence, *, translated_metrics=False, dataset_joiners=False,comparison_context=None,bound_duration_spelling=False):
    """Return a rejection reason; semantic checking still follows this gate."""
    if type(translated_metrics) is not bool:raise ValueError('Invalid metric translation policy')
    if type(dataset_joiners) is not bool:raise ValueError('Invalid dataset joiner policy')
    if type(bound_duration_spelling) is not bool:raise ValueError('Invalid bound duration spelling policy')
    if comparison_context is not None and not isinstance(comparison_context,dict):
        raise ValueError('Invalid comparison display context')
    author_headers={}
    if comparison_context is not None:
        from services.deep_research.comparison_table_context import author_headers as resolve_headers
        author_headers=resolve_headers(claim,evidence,comparison_context)
    text = str(claim.get('text', ''))
    conditions = claim.get('conditions') or {}
    if isinstance(conditions, dict):
        text += ' ' + ' '.join(str(v) for v in conditions.values())
    if bound_duration_spelling:
        text = normalize_bound_duration_spelling(text,claim,evidence)
    metric_mentions = {(v, m.upper()) for m, v in _METRIC.findall(text)}
    unit_mentions = {(v, u.upper()) for v, u in _UNIT.findall(text)}
    bindings = claim.get('tableBindings')
    # Location can point to a table caption containing explicit prose. Only
    # cell-derived quotations need column binding; prose still goes through
    # exact-number and semantic checks, even beside an unverified table.
    table_sources = {e['evidenceId']: e for e in evidence
                     if e.get('tableData') or 'Table row ' in e.get('quote', '')
                     or re.search(r'\|[^\n]*\|', e.get('quote', ''))}
    if not table_sources and not bindings:
        return None
    if not metric_mentions and not unit_mentions and not bindings:
        return None
    prose_measurements = set()
    for item in evidence:
        if item['evidenceId'] in table_sources:
            continue
        quote = item.get('quote', '')
        prose_measurements.update((v, m.upper()) for m, v in _METRIC.findall(quote))
        prose_measurements.update((v, u.upper()) for v, u in _UNIT.findall(quote))
    if not isinstance(bindings, list) or not bindings:
        return 'missing_table_bindings' if (metric_mentions | unit_mentions) - prose_measurements else None
    # An anonymous slash-separated series does not expose dataset/value pairing.
    if re.search(r'\d\s*[/／]\s*\d', text):
        return 'ambiguous_table_series'
    supported = set(prose_measurements)
    for binding in bindings:
        if not isinstance(binding, dict):
            return 'invalid_table_binding'
        if not isinstance(binding.get('evidenceId'), str):
            return 'invalid_table_binding'
        source = table_sources.get(binding['evidenceId'])
        if not source:
            return 'table_binding_outside_citation'
        packet = visible_table_packet(source.get('tableData'), source.get('quote', ''))
        group_index, row_number = binding.get('groupIndex'), binding.get('rowNumber')
        if (not packet or type(group_index) is not int or type(row_number) is not int
                or not 0 <= group_index < len(packet['groups'])):
            return 'unverified_table_cell'
        dataset, metrics = packet['groups'][group_index]
        row = next((row for row in packet['rows'] if row[0] == row_number), None)
        metric = binding.get('metric')
        if not row or metric not in metrics:
            return 'unverified_table_cell'
        column = sum(len(g[1]) for g in packet['groups'][:group_index]) + metrics.index(metric)
        value = row[2][column]
        if binding.get('value') != value:
            return 'table_cell_mismatch'
        # Hierarchical headers require every level (e.g. cohort and aggregate)
        # to be displayed, without forcing the parser's separator into prose.
        right_boundary = r'(?![a-z0-9_+\-])' if dataset_joiners else r'(?![a-z0-9])'
        dataset_visible = all(any(re.search(r'(?<![a-z0-9])' + re.escape(_dataset_key(label, dataset_joiners)) + right_boundary, _dataset_key(text, dataset_joiners))
                                  for label in (part, dataset_label(part)))
                              for part in dataset.split(' / '))
        author_column=(row[1].strip().casefold()=='ours' and source['evidenceId'] in author_headers)
        if (not dataset_visible or not (_method_visible(row[1], text) or author_column)
                or not (_metric_visible(metric,text,translated_metrics)
                    or bound_duration_spelling and any(label in text for label in
                        _DURATION_LABELS.get(_duration_metric_key(metric), ())))
                or _key(value) not in _key(text)):
            return 'table_condition_not_displayed'
        match = re.fullmatch(rf'({_VALUE})([A-Za-z]*)', value)
        if match:
            supported.add((match[1], metric.upper()))
            if match[2]:
                supported.add((match[1], match[2].upper()))
            if metric.upper() == 'PSNR':
                supported.add((match[1], 'DB'))
    if not (metric_mentions | unit_mentions) <= supported:
        return 'unbound_table_measurement'
    return None


def _metric_visible(metric,text,translated):
    # Only literal column-name translations. No method/dataset aliases, unit
    # conversions, inferred synonyms or semantic approval are supplied here.
    if _key(metric) in _key(text):return True
    labels={'size':('大小',),'mem':('内存',)} if translated else {}
    return any(label in text for label in labels.get(metric.casefold(),()))
