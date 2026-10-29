"""Exact quantity spelling equivalence; never changes a quoted source."""
from __future__ import annotations

import re
from decimal import Decimal


_SCALES = {'十': 1, '百': 2, '千': 3, '万': 4, '十万': 5, '百万': 6,
           '千万': 7, '亿': 8, '十亿': 9, '百亿': 10, '千亿': 11, '万亿': 12}
_NUMBER = re.compile(
    r'(?<![A-Za-z0-9_.,])(?P<number>[-+]?\d(?:[\d,]*\d)?(?:\.[\d,]*\d)?(?:[eE][-+]?\d+)?)'
    r'(?:\s*(?P<scale>万亿|千亿|百亿|十亿|千万|百万|十万|亿|万|千|百|十))?'
    r'(?:\s*(?P<unit>[%％x×倍]))?')
_VALID_NUMBER = re.compile(
    r'(?P<sign>[-+]?)(?P<integer>\d+|\d{1,3}(?:,\d{3})+)'
    r'(?:\.(?P<fraction>\d+))?(?:[eE](?P<exponent>[-+]?\d+))?\Z')
_WORDS = dict(zip(('zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve'), range(13)))
_WORD_COUNTS = re.compile(r'(?<![A-Za-z0-9_])(?:(?P<sign>minus|negative|plus|positive|[-−+])\s*)?'
    r'(?P<word>zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)'
    r'[\s\-‐‑–]+(?:dimensions?|dimensional|components?|channels?|outputs?|views?|frames?|images?|'
    r'samples?|trials?|runs?|scenes?|layers?|stages?|phases?|steps?|seeds?|points?|iterations?|groups?)\b', re.I)
_CHINESE_COUNTS = re.compile(r'(?<![A-Za-z0-9_第零一二两三四五六七八九十百千万亿点.])'
    r'(?P<sign>[负正+＋\-−])?\s*(?P<word>[零一二两三四五六七八九十]{1,3})\s*'
    r'(?P<count_unit>个|维|次|帧|层|组|张|条|篇|种|项)')
_CHINESE_EXPANDED_COUNTS = re.compile(r'(?<![A-Za-z0-9_第零一二两三四五六七八九十百千万亿点.])'
    r'(?P<sign>[负正+＋\-−])?\s*(?P<word>[零一二两三四五六七八九十百千万亿]{1,12})\s*'
    r'(?P<count_unit>个|维|次|帧|层|组|张|条|篇|种|项)')
_CHINESE_FACTORS=re.compile(r'(?<![A-Za-z0-9_第零一二两三四五六七八九十百千万亿点.])'
    r'(?P<sign>[负正+＋\-−])?(?P<word>[零一二两三四五六七八九十百千万亿]{1,12}'
    r'(?:点[零一二三四五六七八九]{1,12})?)\s*倍')
_PARAMETER_ID = re.compile(r'(?<![A-Za-z0-9_])[α-ωΑ-Ω]_?\d{1,2}(?![0-9_.%％])')
_ARTIFACT = re.compile(r'(?:(?:\d+|[零一二两三四五六七八九十]+)\s*维\s*)?'
    r'(?:向量|矩阵|张量|数组|编码|表示|输出)(?!个|组|次)')
_COLLECTIVE_DATA = re.compile(r'(?:数字|数值|分量|特征)(?!个|组|次)')
_OUTPUT_CONTEXT = re.compile(r'(?:输出|返回|生成|产生|得到|给出|形成|映射[为成]|是|为)(?:了|成|为)?\s*$')
_EXPLICIT_COUNT = re.compile(r'(?:只(?:能)?|仅(?:能)?|恰好|正好|总共|共|唯一|至少|至多|最多|最少|不超过|超过)'
    r'(?:会|能够)?(?:输出|返回|生成|产生|得到|给出|形成|映射[为成]|是|为)(?:了|成|为)?\s*$')
_CONCEPTUAL_OBJECT = re.compile(r'(?:可学习|可训练|可调节|平衡|调节|数学|标量|优化)?'
    r'(?:参数|变量|目标(?:函数)?|损失(?:函数)?|约束|公式|表达式|权重)')
_CARDINAL_CONTEXT = re.compile(r'(?:只有|仅有|只|仅|唯一|恰好|正好|总共|共|至少|至多|最多|最少|不超过|超过)'
    r'[^，,；;。.!?！？\n]{0,12}$')
_IMAGE_COLLECTION = re.compile(r'(?:(?:单目|多目|多视角|动态|静态|场景|训练|输入|校准|连续|带时间标签的)\s*){0,4}'
    r'(?:图像|图片|照片|视频帧)(?!组)')
_COLLECTION_INTRO = re.compile(r'(?:输入(?:为|是|包括|包含)?|使用|采用|给定|提供|接收|处理|由|以|从)\s*$')


def without_collection_articles(text):
    """An introduced image set is indefinite; explicit group counts stay exact.

    This does not establish the contents, cameras, time coverage or cardinality
    of a set. Those still need source-specific semantic verification.
    """
    # Separate the cardinal from the final 一 in 唯一 for the exact-count parser.
    text = re.sub(r'唯一(?=一\s*组)', '唯一 ', text)
    positions = set()
    for match in _CHINESE_COUNTS.finditer(text):
        prefix, suffix = text[:match.start('word')], text[match.end():].lstrip()
        if (match['word'] == '一' and not match['sign'] and match['count_unit'] == '组'
                and _COLLECTION_INTRO.search(prefix) and _IMAGE_COLLECTION.match(suffix)
                and not _CARDINAL_CONTEXT.search(prefix)
                and not re.search(r'(?:而非|而不是|不是)', suffix)):
            positions.add(match.start('word'))
    return ''.join(char for i, char in enumerate(text) if i not in positions)


def without_dimensional_labels(text, *, surface_labels=False):
    """Chinese spatial labels parallel 2D/3D/4D, not measured cardinalities.

    Keep feature/vector/output dimensions, ordinals, signs, counts and ratios.
    The independent semantic verifier still checks the dimensional identity.
    """
    nouns='高斯|空间|场景|几何|模型|重建|点云|辐射场'
    if surface_labels is True:
        nouns+='|椭圆盘|圆盘|盘片|盘'
    return re.sub(r'(?<![A-Za-z0-9_第负正+＋\-−零一二两三四五六七八九十百千万亿])'
        r'[234二两三四]维(?=(?:的)?(?:'+nouns+'))','',text)


def without_conceptual_articles(text):
    """Remove only indefinite 一 before a mathematical object, never its value.

    Chinese uses 一个 like English a/an in introducing a parameter or objective.
    Explicit cardinality, signs, Arabic digits and empirical count nouns remain.
    This lexical distinction is not a semantic verdict on the object or claim.
    """
    positions = set()
    for match in _CHINESE_COUNTS.finditer(text):
        if (match['word'] == '一' and not match['sign'] and match['count_unit'] == '个'
                and _CONCEPTUAL_OBJECT.match(text[match.end():].lstrip())
                and not _CARDINAL_CONTEXT.search(text[:match.start('word')])):
            positions.add(match.start('word'))
    return ''.join(char for i, char in enumerate(text) if i not in positions)


def parameter_identifiers(text):
    return {match[0] for match in _PARAMETER_ID.finditer(text)}


def without_parameter_identifiers(text, allowed=None):
    return _PARAMETER_ID.sub(lambda m: '' if allowed is None or m[0] in allowed else m[0], text)


def _chinese_count(word, *, expanded=False):
    values = dict(zip('零一二两三四五六七八九', (0,1,2,2,3,4,5,6,7,8,9)))
    if word in values: return values[word]
    if word == '十': return 10
    if word in ('十一', '十二'): return 10 + values[word[1]]
    if expanded:
        # Parse literal cardinal spellings, not arithmetic or approximate 上百.
        total = section = 0; digit = None; last_small = 10000; last_large = 10**12
        for char in word:
            if char in values:
                if digit not in (None, 0): return None
                digit = values[char]
            elif char in '十百千':
                unit = {'十':10,'百':100,'千':1000}[char]
                if unit >= last_small or (digit is None and not (char == '十' and section == 0)):
                    return None
                section += (1 if digit is None else digit) * unit
                digit = None; last_small = unit
            elif char in '万亿':
                unit = {'万':10000,'亿':100000000}[char]
                if unit >= last_large: return None
                section += digit or 0
                if not section: return None
                total += section * unit
                section = 0; digit = None; last_small = 10000; last_large = unit
            else:
                return None
        return total + section + (digit or 0)
    return None


def _count_words(text, *, relative_references=False, artifact_references=False, expanded_counts=False):
    for match in _WORD_COUNTS.finditer(text):
        # Do not misread the tail of an unsupported compound (twenty-three)
        # as three, or invent the number of the remaining dimensions.
        if re.search(r'[A-Za-z][\-‐‑–]\s*$', text[:match.start('word')]): continue
        value = _WORDS[match['word'].lower()]
        yield -value if (match['sign'] or '').lower() in {'minus','negative','-','−'} else value
    for match in (_CHINESE_EXPANDED_COUNTS if expanded_counts else _CHINESE_COUNTS).finditer(text):
        # 上一帧/下一组 locate an adjacent item; they do not report its count.
        # Keep 前两帧/后四组 and all signed counts as actual quantities.
        if (relative_references and match['word'] == '一' and not match['sign']
                and re.search(r'[上下前后]\s*$', text[:match.start('word')])):
            continue
        if artifact_references and match['word'] == '一' and not match['sign']:
            prefix, suffix = text[:match.start('word')], text[match.end():].lstrip()
            artifact = ((_ARTIFACT.match(suffix) if match['count_unit'] == '个' else
                         _COLLECTIVE_DATA.match(suffix) if match['count_unit'] == '组' else None))
            # In 输出一组数字/输出一个7维向量, 一 introduces the data object.
            # Explicit cardinality, signed/Arabic counts, samples, trials,
            # views and experimental groups remain measured quantities.
            if artifact and _OUTPUT_CONTEXT.search(prefix) and not _EXPLICIT_COUNT.search(prefix):
                continue
        value = _chinese_count(match['word'], expanded=expanded_counts)
        if value is not None:
            yield -value if match['sign'] in {'负','-','−'} else value


def number_display(identity):
    """Readable exact check detail; do not expand hostile/large exponents."""
    match = re.fullmatch(r'(-?\d+)e(-?\d+)([%x]?)', identity)
    if not match: return identity
    coefficient, exponent, unit = match.groups()
    if len(coefficient) <= 24 and len(exponent) <= 3 and -6 <= int(exponent) <= 8:
        return format(Decimal(coefficient + 'e' + exponent), 'f') + unit
    return identity


def measurement_numbers(text: str, *, word_counts=False, relative_references=False,
                        artifact_references=False, conceptual_articles=False, expanded_counts=False,
                        chinese_factors=False, collection_articles=False) -> set[str]:
    """Compare decimal/scientific/grouped/Chinese-scale forms exactly.

    Store a coefficient and exponent, without float rounding, Decimal context
    rounding or expanding large exponents. Malformed comma groups stay opaque;
    their pieces must not accidentally support an unrelated smaller number.
    Percentages and factors retain distinct identities. Other physical units
    and the relation between quantities still require semantic verification.
    Opt-in count words recognize directly written zero-to-twelve quantities
    beside count nouns. They do not infer remaining counts or evaluate sums.
    """
    if conceptual_articles is True:
        text = without_conceptual_articles(text)
    if collection_articles is True:
        text = without_collection_articles(text)
    numbers = set()
    if chinese_factors is True:
        digits=dict(zip('零一二三四五六七八九','0123456789'))
        for match in _CHINESE_FACTORS.finditer(text):
            integer,separator,fraction=match['word'].partition('点')
            value=_chinese_count(integer,expanded=True)
            if value is None:
                numbers.add('literal:'+match[0]);continue
            literal=('-' if match['sign'] in {'负','-','−'} else '')+str(value)
            if separator:
                literal+='.'+''.join(digits[ch] for ch in fraction)
            numbers.update(measurement_numbers(literal+'倍'))
    for match in _NUMBER.finditer(text):
        literal = match.group('number')
        parsed = _VALID_NUMBER.fullmatch(literal)
        exponent_text = parsed.group('exponent') if parsed else None
        # Bound conversion of hostile exponents, not the expanded number size.
        # Unsupported spellings can match themselves, but gain no equivalence.
        if (not parsed or (exponent_text and len(exponent_text.lstrip('+-')) > 9)
                or text[match.end():].startswith('分之')):
            numbers.add('literal:' + match.group())
            continue
        fraction = parsed.group('fraction') or ''
        coefficient = (parsed.group('integer').replace(',', '') + fraction).lstrip('0')
        exponent = int(exponent_text or '0') - len(fraction) + _SCALES.get(match.group('scale'), 0)
        if coefficient:
            trimmed = coefficient.rstrip('0')
            exponent += len(coefficient) - len(trimmed)
            coefficient = ('-' if parsed.group('sign') == '-' else '') + trimmed
        else:
            coefficient, exponent = '0', 0
        unit = match.group('unit')
        suffix = '%' if unit in {'%', '％'} else 'x' if unit in {'x', '×', '倍'} else ''
        numbers.add(f'{coefficient}e{exponent}{suffix}')
    if word_counts is True:
        for value in _count_words(text, relative_references=relative_references,
                                 artifact_references=artifact_references, expanded_counts=expanded_counts):
            numbers.update(measurement_numbers(str(value)))
        if expanded_counts:
            for match in _CHINESE_EXPANDED_COUNTS.finditer(text):
                if _chinese_count(match['word'], expanded=True) is None:
                    numbers.add('literal:' + match[0])
    return numbers
