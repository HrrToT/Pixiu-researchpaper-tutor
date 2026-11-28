"""Exact quantity spelling equivalence; never changes a quoted source."""
from __future__ import annotations

import re
from decimal import Decimal


def normalize_interpolation_kernel_labels(text):
    # 双三次 names the bicubic kernel. Preserve independent repetition counts.
    return re.sub(r'双三次(?=(?:插值|重采样))', '双立方', text)


_SCALES = {'十': 1, '百': 2, '千': 3, '万': 4, '十万': 5, '百万': 6,
           '千万': 7, '亿': 8, '十亿': 9, '百亿': 10, '千亿': 11, '万亿': 12}
_NUMBER = re.compile(
    r'(?<![A-Za-z0-9_.,])(?P<number>[-+]?\d(?:[\d,]*\d)?(?:\.[\d,]*\d)?(?:[eE][-+]?\d+)?)'
    r'(?:\s*(?P<scale>万亿|千亿|百亿|十亿|千万|百万|十万|亿|万|千|百|十))?'
    r'(?:\s*(?P<unit>[%％x×倍]))?')
_VALID_NUMBER = re.compile(
    r'(?P<sign>[-+]?)(?P<integer>\d+|\d{1,3}(?:,\d{3})+)'
    r'(?:\.(?P<fraction>\d+))?(?:[eE](?P<exponent>[-+]?\d+))?\Z')
_ENGLISH_FACTOR_SUFFIX = re.compile(r'(?<=\d)\s+times(?=\s+(?:smaller|larger|higher|lower|wider|narrower)\b)', re.I)
_ENGLISH_UPSAMPLE_SCHEDULE = re.compile(
    r'\b(upsampl(?:e|es|ed|ing)\s+)twice(?=\s+after\s+\d+\s+and\s+\d+\s+iterations?\b)', re.I)
_DISTRIBUTED_UPSAMPLE_SCHEDULE = re.compile(
    r'(?<![0-9.,+\-])(?P<first>\d+)\s*(?:和|与|及|、)\s*(?P<second>\d+)\s*(?:次)?迭代后\s*各上采样一次')
_WORDS = dict(zip(('zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve'), range(13)))
_SMALL_CARDINAL = '|'.join(_WORDS)
_FACTOR_OF = re.compile(
    rf'\bfactor\s+of\s+(?P<sign>minus\s+|negative\s+|plus\s+|positive\s+|[-+−])?'
    rf'(?P<count>{_SMALL_CARDINAL}|\d+(?:\.\d+)?)\b'
    r'(?![.,]\d|\s+(?:hundred|thousand|million|billion|point|to|times)\b|[-–—]\s*\d)', re.I)
_EN_COUNT_PREFIX = r'(?<![\w.,+\-−])(?P<sign>(?:minus|negative|plus|positive)\s+|[-+−])?'
_ZH_COUNT_PREFIX = (r'(?<![\d.,+\-−负正第零一二两三四五六七八九十百千万亿点])'
                    r'(?P<sign>[负正+\-−])?')
_STEP_COUNT_EN = re.compile(
    _EN_COUNT_PREFIX + rf'(?P<count>{_SMALL_CARDINAL}|\d+)\s+'
    r'(?:(?:zoom[-‐‑\s]+in|refinement)\s+)?steps?\b', re.I)
_STEP_COUNT_ZH = re.compile(
    _ZH_COUNT_PREFIX +
    r'(?P<count>\d+|[零一二两三四五六七八九十]+)\s*(?:个\s*)?(?:放大)?步(?!骤法)')
_IMAGE_COUNT_EN = re.compile(
    _EN_COUNT_PREFIX + rf'(?P<count>{_SMALL_CARDINAL}|both|\d+)\s+images?\b', re.I)
_IMAGE_COUNT_ZH = re.compile(
    _ZH_COUNT_PREFIX +
    r'(?P<count>\d+|[零一二两三四五六七八九十]+)\s*张\s*(?:图像|图片|图(?!表|示))')
_REUSED_NETWORK = re.compile(r'(?:使用|(?:沿|复|重)?用)\s*同\s*一\s*个\s*网络')
_SINGLE_FORWARD_PASS = re.compile(r'\b(?:single|one)(?=[\s-]+forward[\s-]+pass\b)', re.I)
_SH_BAND_AT_INTERVAL = re.compile(
    r'\b(?P<verb>introduc(?:e|es|ed|ing)\s+)one'
    r'(?=\s+band\s+of\s+(?:the\s+)?SH\s+after\s+every\s+[1-9][0-9,]*\s+iterations?\b)', re.I)
_GAUSSIAN_REPLACEMENT_COUNT = re.compile(
    r'(?P<prefix>\breplac(?:e|es|ed|ing)\s+(?:such\s+|these\s+|the\s+)?(?:large\s+)?Gaussians\s+(?:by|with)\s+)'
    r'(?P<count>' + '|'.join(_WORDS) + r')(?=\s+new\s+(?:Gaussians|ones)\b)', re.I)
_GAUSSIAN_FIGURE_SPLIT = re.compile(
    r'(?P<prefix>\brepresented\s+by\s+(?:one|a)\s+large\s+(?:splat|Gaussian),\s+we\s+split\s+it\s+in(?:to)?\s+)'
    r'two(?=\s*[.!?])', re.I)
_RANGE_SCALE = re.compile(
    r'(?<![A-Za-z0-9_.,+\-−])(?P<low>[0-9]+(?:\.[0-9]+)?)'
    r'(?:-|\s*(?:[–—~～]|至|到|\bto\b)\s*)'
    r'(?P<high>[0-9]+(?:\.[0-9]+)?)\s*'
    r'(?P<scale>(?>thousand\b|million\b|billion\b|万亿|千亿|百亿|十亿|千万|百万|十万|亿|万|千|百|十))'
    r'(?!分之|[万亿千百十]|\s*[%％×倍]|[-‐‑]fold\b)', re.I | re.ASCII)
_ENGLISH_SCALES = {'thousand': 3, 'million': 6, 'billion': 9}
_DIMENSION_SEPARATOR = r'\s*[×xX]\s*'
_DIMENSION_VALUES = r'[0-9]+(?:' + _DIMENSION_SEPARATOR + r'[0-9]+)+'
_DIMENSION_SERIES = re.compile(r'(?<![A-Za-z0-9_.,+\-−×])' + _DIMENSION_VALUES
                               + r'(?:(?=px\b|pixels?\b)|(?![A-Za-z0-9_×]|[.,][0-9]|'
                               + _DIMENSION_SEPARATOR + r'))', re.I)
_ATTACHED_RESOLUTION_ARTICLE = re.compile(
    r'\b(?P<prefix>(?:at|to|with)\s+)a(?=' + _DIMENSION_VALUES + r'\s+resolution\b)', re.I)
_ATTACHED_RESOLUTION_PROSE = re.compile(
    r'(?<![A-Za-z0-9_.,+\-−×])' + _DIMENSION_VALUES + r'(?=for\s+(?:all|each|the|both)\b)', re.I)
_WORD_COUNTS = re.compile(r'(?<![A-Za-z0-9_])(?:(?P<sign>minus|negative|plus|positive|[-−+])\s*)?'
    r'(?P<word>zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)'
    r'[\s\-‐‑–]+(?:dimensions?|dimensional|components?|channels?|outputs?|views?|frames?|images?|'
    r'samples?|trials?|runs?|scenes?|layers?|stages?|phases?|steps?|seeds?|points?|iterations?|groups?)\b', re.I)
_EVALUATION_COUNTS = re.compile(
    r'(?<![A-Za-z0-9_‐‑–-])(?:(?P<sign>minus|negative|plus|positive|[-−+])\s*)?'
    r'(?P<count>' + '|'.join(_WORDS) + r'|both)\s+(?=datasets?\b|configurations?\b)', re.I)
_THOUSANDS_OF_ITERATIONS = re.compile(
    r'(?<![A-Za-z0-9_.,$€£+\-])(?P<count>[1-9][0-9]{0,5}(?:\.[0-9]{1,3})?)k'
    r'(?=(?:\s*(?:,\s*(?:and\s+|or\s+)?|\s+(?:and|or)\s+|[、，和与或]\s*)'
    r'[1-9][0-9]{0,5}(?:\.[0-9]{1,3})?k)*(?:\s+iterations?\b|\s*(?:次\s*)?迭代))', re.I)
_LISTED_ITERATION_COUNT = re.compile(r'(?<![\d.,])\d{1,9}(?:,\d{3}){0,2}\s*(?:步(?!长)|(?:次\s*)?迭代)')
_LISTED_ITERATION_REFERENCE = re.compile(r'这(?P<count>两)项计数(?=\s*(?:相加|求和))')
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
_IMAGE_PAIR_INTRODUCTION = re.compile(
    r'从一\s*张\s*(?P<source>图像|图片|图)\s*(?P<verb>生成|构造|得到)\s*'
    r'另一\s*张\s*(?P<target>图像|图片|图)(?=\s*(?:[，,；;。.!?！？]|$))')
_IMAGE_PAIR_COUNT_CONTEXT = re.compile(
    r'(?:每(?:次|轮|步|帧|张|个样本)|逐(?:次|张|帧))[^，,；;。.!?！？\n]{0,12}$')
_SPATIAL_CARDINAL_CONTEXT = re.compile(
    r'(?:只有|仅有|只|仅|唯一|恰好|正好|总共|至少|至多|最多|最少|不超过|超过)'
    r'[^，,；;。.!?！？\n]{0,12}$'
    r'|共(?:计)?(?:有|使用|采用|包含|输出|生成|返回|具有)?(?:了)?\s*$')
_IMAGE_COLLECTION = re.compile(r'(?:(?:单目|多目|多视角|动态|静态|场景|训练|输入|校准|连续|带时间标签的)\s*){0,4}'
    r'(?:图像|图片|照片|视频帧)(?!组)')
_COLLECTION_INTRO = re.compile(r'(?:输入(?:为|是|包括|包含)?|使用|采用|给定|提供|接收|处理|由|以|从)\s*$')
_GEOMETRIC_COLLECTION_INTRO = re.compile(r'(?:表示|建模|坍缩|近似|分解|离散|重建)(?:为|成)\s*$')
_GEOMETRIC_COLLECTION = re.compile(r'(?:(?:有方向的|有朝向的|带朝向的|定向的|平面|二维|三维|2D|3D)\s*){0,5}'
    r'(?:高斯(?:圆盘|椭圆盘|盘|面片|基元|点)?|椭圆盘|圆盘|盘片|面片|表面片|基元)'
    r'(?!特征|向量|矩阵|张量|数组|编码|输出|通道|参数)',re.I)
_GEOMETRIC_COLLECTION_WITH_MODIFIERS = re.compile(
    r'(?:[^，,；;。.!?！？\n的]{1,32}的\s*){0,2}'
    r'(?:(?:(?:有方向|有朝向|带朝向|定向)的?|平面|二维|三维|2D|3D)\s*){0,5}'
    # Commit to the longest object name: a failed parameter suffix must not
    # backtrack from 高斯圆盘 to 高斯 and hide an actual group count.
    r'(?>高斯(?:椭圆盘|圆盘|盘片|盘|面片|基元|点)?|椭圆盘|圆盘|盘片|面片|表面片|基元)'
    r'(?!(?:的\s*)?(?:特征|向量|矩阵|张量|数组|编码|输出|通道|参数))',re.I)
_SPATIAL_DIMENSION_TAG = re.compile(r'(?<![A-Za-z0-9_第负正+＋\-−±∓/／零一二两三四五六七八九十百千万亿])'
                                  r'[234二两三四]维')
_DIMENSION_VALUE_NOUN = re.compile(r'(?:的\s*)?(?:度|向量|特征|矩阵|张量|数组|编码|输出|输入|通道|分量|参数|自由度|'
                                 r'嵌入|潜变量|embedding\b|vector\b|tensor\b|feature\b|channel\b|latent\b)',re.I)
_DIMENSION_VALUE_PREFIX = re.compile(r'(?:向量|特征|矩阵|张量|数组|编码|输出|输入|通道|分量|参数|自由度|嵌入|潜变量|'
                                   r'embedding|vector|tensor|feature|channel|latent)'
                                   r'[^，,；;。.!?！？\n]{0,20}(?:(?:降|压缩|压|映射|投影|降维)[为至到成]|维数[为是]?|维度[为是]?|为|是)\s*$',re.I)


def _spatial_dimension_tags(text, *, cardinal_context=_CARDINAL_CONTEXT):
    """Low-dimensional labels have the same lexical role as English 2D/3D/4D.

    Explicit feature/vector/output dimension contexts stay numeric. Other
    object names are not enumerated here; their spatial identity still needs
    independent semantic source support. This does not approve any claim.
    """
    def replace(match):
        before,after=text[:match.start()],text[match.end():].lstrip()
        if _DIMENSION_VALUE_NOUN.match(after) or _DIMENSION_VALUE_PREFIX.search(before) or cardinal_context.search(before):
            return match[0]
        return ''
    return _SPATIAL_DIMENSION_TAG.sub(replace,text)


def without_collection_articles(text, *, geometric=False):
    """An introduced image set is indefinite; explicit group counts stay exact.

    This does not establish the contents, cameras, time coverage or cardinality
    of a set. Those still need source-specific semantic verification.
    """
    # Separate the cardinal from the final 一 in 唯一 for the exact-count parser.
    text = re.sub(r'唯一(?=一\s*组)', '唯一 ', text)
    geometry = (_GEOMETRIC_COLLECTION_WITH_MODIFIERS if type(geometric) is int and geometric==2
                else _GEOMETRIC_COLLECTION if geometric is True else None)
    positions = set()
    for match in _CHINESE_COUNTS.finditer(text):
        prefix, suffix = text[:match.start('word')], text[match.end():].lstrip()
        # “用一组高斯表示场景” introduces a representation, not an
        # experimental group count. Require the explicit geometric object AND
        # representation purpose; “采用一组作为对照” remains quantitative.
        shape=geometry.match(suffix) if geometry is not None else None
        representation_use=(type(geometric) is int and geometric==2 and shape is not None
            and re.search(r'(?:使用|采用|(?<![采使])用)\s*$',prefix)
            and re.match(r'\s*(?:（[^（）\r\n。]{1,90}）|\([^()\r\n.]{1,90}\))?\s*'
                         r'(?:表示|建模|近似|重建)(?:场景|物体|表面|几何|环境|空间)',suffix[shape.end():]))
        contrast_scope = re.split(r'[。！？!?\r\n]', suffix, maxsplit=1)[0] if shape else suffix
        if (match['word'] == '一' and not match['sign'] and match['count_unit'] == '组'
                and (_COLLECTION_INTRO.search(prefix) and _IMAGE_COLLECTION.match(suffix)
                     or geometry is not None and _GEOMETRIC_COLLECTION_INTRO.search(prefix) and shape
                     or representation_use)
                and not _CARDINAL_CONTEXT.search(prefix)
                and not re.search(r'(?:而非|而不是|不是)', contrast_scope)):
            positions.add(match.start('word'))
    return ''.join(char for i, char in enumerate(text) if i not in positions)


def without_dimensional_labels(text, *, surface_labels=False):
    """Chinese spatial labels parallel 2D/3D/4D, not measured cardinalities.

    Keep feature/vector/output dimensions, ordinals, signs, counts and ratios.
    The independent semantic verifier still checks the dimensional identity.
    """
    if type(surface_labels) is int and surface_labels==3:return _spatial_dimension_tags(text)
    if type(surface_labels) is int and surface_labels==4:
        # 共 is a count prefix only in count syntax; it is also a character in
        # compound predicates such as 共同表示. Numeric roles remain guarded.
        return _spatial_dimension_tags(text,cardinal_context=_SPATIAL_CARDINAL_CONTEXT)
    nouns='高斯|空间|场景|几何|模型|重建|点云|辐射场'
    if surface_labels is True:
        nouns+='|椭圆盘|圆盘|盘片|盘'
    elif type(surface_labels) is int and surface_labels==2:
        nouns+='|椭圆盘|圆盘|盘片|盘|表面(?:片|元)|面片|薄片|片(?!段|特征|向量|矩阵|张量|数组|编码|输出|通道)'
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
    if identity.startswith('dimensions:'):
        return identity.removeprefix('dimensions:').replace('x', '×')
    kind, separator, value = identity.partition(':')
    if separator and kind in {'steps', 'images'}:
        return number_display(value) + (' 步' if kind == 'steps' else ' 张图像')
    match = re.fullmatch(r'(-?\d+)e(-?\d+)([%x]?)', identity)
    if not match: return identity
    coefficient, exponent, unit = match.groups()
    if len(coefficient) <= 24 and len(exponent) <= 3 and -6 <= int(exponent) <= 8:
        return format(Decimal(coefficient + 'e' + exponent), 'f') + unit
    return identity


def stepwise_quantity_view(text):
    """Keep image and step counts distinct while comparing translated evidence."""
    def cardinal(raw):
        if raw.isdecimal():
            return raw
        if raw.lower() in _WORDS:
            return str(_WORDS[raw.lower()])
        value = _chinese_count(raw, expanded=True)
        return str(value) if value is not None else None

    def signed(count, sign):
        negative = (sign or '').strip().lower() in {'负', '-', '−', 'minus', 'negative'}
        return '-' + count if negative else count

    # Leave the object words in the text when masking a referential article.
    # Explicit bounds on the number of networks still require numeric evidence.
    text = _REUSED_NETWORK.sub(
        lambda m: m[0] if _CARDINAL_CONTEXT.search(text[:m.start()]) else m[0].replace('一', ''),
        text)
    text = _FACTOR_OF.sub(
        lambda m: signed(cardinal(m['count']) or m['count'], m['sign']) + '×', text)
    typed = set()

    def extract_chinese_factor(match):
        typed.update(measurement_numbers(match[0], chinese_factors=True))
        return ' '

    text = _CHINESE_FACTORS.sub(extract_chinese_factor, text)
    for pattern, kind in ((_STEP_COUNT_EN, 'steps'), (_STEP_COUNT_ZH, 'steps'),
                          (_IMAGE_COUNT_EN, 'images'), (_IMAGE_COUNT_ZH, 'images')):
        def extract(match):
            count = '2' if match['count'].lower() == 'both' else cardinal(match['count'])
            if count is None:
                return match[0]
            typed.update(f'{kind}:{number}' for number in measurement_numbers(signed(count, match['sign'])))
            return ' '

        text = pattern.sub(extract, text)
    return text, typed


def normalize_explicit_quantity_phrases(text, *, shared_range_scale=False, gaussian_replacement_counts=False,
                                        image_pair_articles=False, explicit_forward_pass=False,
                                        explicit_sh_band_schedule=False, evaluation_counts=False,
                                        gaussian_figure_split=False, thousands_of_iterations=False):
    """Normalize number checks only. Preserve original quotes for semantic review."""
    text = _ENGLISH_FACTOR_SUFFIX.sub('×', text)
    text = _ENGLISH_UPSAMPLE_SCHEDULE.sub(r'\g<1>2 times', text)
    if thousands_of_iterations:
        text = _THOUSANDS_OF_ITERATIONS.sub(r'\g<count>e3', text)

        def listed_count_reference(match):
            # The phrase refers to two counts already present in the prose.
            # Keep the operation-specific quantities for factual review.
            preceding = re.split(r'[。！？\n]', text[:match.start()])[-2:]
            if len(_LISTED_ITERATION_COUNT.findall('。'.join(preceding))) == 2:
                return '上述计数'
            return match[0]
        text = _LISTED_ITERATION_REFERENCE.sub(listed_count_reference, text)
    if gaussian_replacement_counts:
        text = _GAUSSIAN_REPLACEMENT_COUNT.sub(
            lambda match: match['prefix'] + str(_WORDS[match['count'].lower()]), text)
    if gaussian_figure_split:
        text = _GAUSSIAN_FIGURE_SPLIT.sub(r'\g<prefix>2', text)
    if explicit_forward_pass:
        text = _SINGLE_FORWARD_PASS.sub('1', text)
    if explicit_sh_band_schedule:
        text = _SH_BAND_AT_INTERVAL.sub(r'\g<verb>1', text)
    if evaluation_counts:
        def evaluation_count(match):
            count = match['count'].lower()
            value = 2 if count == 'both' else _WORDS[count]
            negative = (match['sign'] or '').lower() in {'minus', 'negative', '-', '−'}
            return f'{-value if negative else value} '

        text = _EVALUATION_COUNTS.sub(evaluation_count, text)
    if image_pair_articles:
        # In a transformation description, “a source image and another
        # image” introduces the pair members. Exact or per-input counts and
        # the semantic relationship between the images still need evidence.
        def without_pair_articles(match):
            prefix = text[:match.start()]
            contrast = re.match(r'\s*[,，]\s*(?:而非|而不是|不是)', text[match.end():])
            if _CARDINAL_CONTEXT.search(prefix) or _IMAGE_PAIR_COUNT_CONTEXT.search(prefix) or contrast:
                return match[0]
            return f"从{match['source']}{match['verb']}另{match['target']}"

        text = _IMAGE_PAIR_INTRODUCTION.sub(without_pair_articles, text)

    def distribute(match):
        if match['first'] == match['second']:
            return match[0]
        return f"{match['first']}和{match['second']}次迭代后分别上采样，共两次"

    text = _DISTRIBUTED_UPSAMPLE_SCHEDULE.sub(distribute, text)
    if not shared_range_scale:
        return text

    def expand_range_scale(match):
        scale = match['scale'].lower()
        exponent = _ENGLISH_SCALES[scale] if scale in _ENGLISH_SCALES else _SCALES[scale]
        return f"{match['low']}e{exponent} 到 {match['high']}e{exponent}"

    return _RANGE_SCALE.sub(expand_range_scale, text)


def split_dimension_series(text, *, pdf_word_spacing=False):
    """Keep the exact ordered dimensions together, including in PDF-extracted text."""
    text = _ATTACHED_RESOLUTION_ARTICLE.sub(r'\g<prefix>a ', text)
    if pdf_word_spacing:
        text = _ATTACHED_RESOLUTION_PROSE.sub(r'\g<0> ', text)
    dimensions = set()

    def collect(match):
        if re.search(r'[0-9]\s*[×xX]\s*$', text[:match.start()]):
            return match[0]
        values = re.split(_DIMENSION_SEPARATOR, match[0])
        dimensions.add('dimensions:' + 'x'.join(value.lstrip('0') or '0' for value in values))
        return ' '

    return _DIMENSION_SERIES.sub(collect, text), dimensions


def measurement_numbers(text: str, *, word_counts=False, relative_references=False,
                        artifact_references=False, conceptual_articles=False, expanded_counts=False,
                        chinese_factors=False, collection_articles=False, geometric_collection_articles=False) -> set[str]:
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
        text = without_collection_articles(text,geometric=geometric_collection_articles)
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
