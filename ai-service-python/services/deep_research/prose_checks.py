"""Detect presentation leaks and unbounded source-absence assertions, not truth."""
import re

ABSENCE = re.compile(r'(?:未|没有)(?:给出|报告|提供|进行|测试|验证|覆盖|涵盖|涉及|包含|包括|说明|披露|评估)'
    r'|不(?:包含|包括|涉及|涵盖)|不存在'
    r'|\b(?:does|did|do) not (?:report|provide|test|evaluate|contain|include)'
    r'|\bno (?:experiment|evaluation|evidence)', re.I)
EXPLICIT_ABSENCE = re.compile(r'\b(?:do|does|did) not\b|\bnot (?:report|evaluat|test|consider)'
    r'|\bno experiment|未(?:报告|进行|测试|考虑)|没有', re.I)
_PAPER = re.compile(r'论文|文中|作者|原文|摘要|\b(?:paper|authors?|article|abstract)\b', re.I)
_SCOPED = re.compile(r'当前取得|本次检索|所读片段|选定片段|所选证据|当前片段|已取得(?:的)?片段'
    r'|\b(?:selected|retrieved) (?:passages|evidence)\b', re.I)
_CURRENT_EVIDENCE_SUBJECT = re.compile(
    r'(?:(?:现有|当前)(?:的)?(?:证据|材料|片段)|本次(?:取得|获得|检索|选定)?(?:的)?(?:证据|材料|片段))'
    r'(?:中)?(?:尚|仍)?\s*$'
    r'|\b(?:current|available|obtained) (?:evidence|passages|materials?)(?:\s+still)?\s*$', re.I)
_ALIAS = re.compile(r'(?<![A-Za-z0-9_])(?:E|P)[1-9]\d*(?![A-Za-z0-9_])')
_RAW_ID = re.compile(r'(?<![A-Za-z0-9_])ev_[0-9a-f]{64}(?![A-Za-z0-9_])')
_PUBLICATION_OBJECT = re.compile(r'实验|评测|评估|测试|验证|证据|结果|配置|信息|报告'
    r'|\b(?:experiment|evaluation|test|evidence|result|report|configuration)s?\b', re.I)
_REPORTING_ABSENCE = re.compile(r'未|没有|not (?:report|provide|test|evaluate)|no (?:experiment|evaluation|evidence)', re.I)
_EXTENDED_ABSENCE = re.compile(ABSENCE.pattern +
    r'|(?:未|没有)(?:在|对|就)[^，,。；;！？!?\n]{1,48}?(?:进行)?(?:报告|提供|测试|验证|评估|评测|测量)'
    r'|(?:未|没有)(?:曾|能)(?:给出|报告|提供|测试|验证|评估|披露)', re.I)
_SOURCE_REPORTING_ABSENCE = re.compile(
    r'\b(?:do|does|did|have|has) not\s+(?:yet\s+)?(?:report|provid|give|disclos|describ|present|test|evaluat|benchmark|measur)\w*\b'
    r'|\bno (?:experiment|evaluation|benchmark)s?\b'
    r'|(?:未|没有)(?:曾|能)?(?:报告|提供|给出|说明|披露|测试|验证|评估|评测|测量)'
    r'|(?:未|没有)(?:在|对|就)[^，,。；;！？!?\n]{1,48}?(?:进行)?(?:报告|提供|给出|说明|披露|测试|验证|评估|评测|测量)'
    r'|(?:未|没有)(?:提供|给出|披露)[^，,。；;！？!?\n]{0,24}(?:实验|评测|评估|测试|验证|结果|配置|硬件|划分)', re.I)
_POOL_ABSENCE=re.compile(
    r'(?:提供|所给|当前|现有|所选|选定|本次(?:取得|获得|检索)?)(?:的)?(?:证据|材料|片段)(?:中|里)?'
    r'[^，,。；;！？!?\n]{0,36}(?:未出现|未见|没有出现|不存在|不包含|未包含|未提及|没有)'
    r'|\b(?:provided|supplied|current|available|selected|retrieved) (?:evidence|passages|materials?)'
    r'[^.;!?\n]{0,50}\b(?:absent|missing|not present|does not contain|do not contain)\b'
    r'|\b(?:absent|missing|not present) in (?:the )?(?:provided|supplied|current|available) (?:evidence|passages)\b',re.I)
_INVERTED_POOL_ABSENCE=re.compile(
    r'(?:未|没有)(?:在|于)(?:所)?(?:提供|所给|当前|现有|所选|选定|本次(?:取得|获得|检索)?)(?:的)?'
    r'(?:证据|材料|片段)(?:中|里)?[^，,。；;！？!?\n]{0,24}(?:说明|报告|给出|提供|提及|出现|找到|披露)'
    r'|(?:未|没有)(?:被)?(?:提供|所给|当前|现有|所选|选定)(?:的)?(?:证据|材料|片段)'
    r'[^，,。；;！？!?\n]{0,16}(?:说明|报告|给出|提及|覆盖)'
    r'|\b(?:not|never) (?:described|reported|specified|mentioned|given|provided|found) '
    r'(?:in|by) (?:the )?(?:provided|supplied|current|available|selected|retrieved) (?:evidence|passages|materials?)\b', re.I)
_FORWARD_POOL_REPORTING_ABSENCE=re.compile(
    r'(?:提供|所给|当前|现有|所选|选定|本次(?:取得|获得|检索)?)(?:的)?(?:证据|材料|片段)(?:中|里)?'
    r'[^，,。；;！？!?\n]{0,36}(?:未|没有)(?:说明|报告|给出|提供|提及|披露)', re.I)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def claim_prose(claim):
    yield from _strings(claim.get('text', ''))
    yield from _strings(claim.get('conditions', {}))


def leaks_internal_reference(claim, support, *, table_aliases=False):
    for text in claim_prose(claim):
        if _RAW_ID.search(text):
            return True
        pattern=re.compile(r'(?<![A-Za-z0-9_])(?:E|P|T)[1-9]\d*(?![A-Za-z0-9_])') if table_aliases else _ALIAS
        for match in pattern.finditer(text):
            alias = match.group()
            # A genuine paper symbol (e.g. E1 in an equation) retains its name.
            # Evidence aliases in a citation context never become public symbols.
            contextual = bool(re.search(r'(?:证据|来源|引文|根据)\s*$', text[:match.start()])
                              or re.match(r'\s*(?:表\s*\d|片段|来源|第\s*\d+\s*页)', text[match.end():]))
            token = re.compile(r'(?<![A-Za-z0-9_])' + re.escape(alias) + r'(?![A-Za-z0-9_])')
            if contextual or not any(token.search(item.get('quote', '')) for item in support):
                return True
    return False


def absence_not_established(claim, support, *, scope_version=0):
    if type(scope_version) is int and scope_version in (6,7) and claim.get('kind') in {'reported','inference'}:
        # A claim's selected references cannot certify what is absent from the
        # task's entire acquired pool. Positive, evidence-bounded uncertainty
        # (e.g. insufficient to establish alignment) remains available.
        if any(_POOL_ABSENCE.search(text) for text in claim_prose(claim)):
            return True
        if scope_version==7 and any(_INVERTED_POOL_ABSENCE.search(text) or _FORWARD_POOL_REPORTING_ABSENCE.search(text)
                                   for text in claim_prose(claim)):
            return True
    reporting_scope = type(scope_version) is int and scope_version in (2,3,4,5,6,7)
    source_pattern = _SOURCE_REPORTING_ABSENCE if reporting_scope else EXPLICIT_ABSENCE
    explicit = any(source_pattern.search(item.get('quote', '')) for item in support)
    if explicit:
        return False  # Independent semantic verification still checks the exact subject/scope.
    factual = claim.get('kind') in {'reported', 'inference'}
    for text in claim_prose(claim):
        for sentence in re.split(r'[。！？；;.!?\n]', text):
            for missing in (_EXTENDED_ABSENCE if reporting_scope else ABSENCE).finditer(sentence):
                prefix = sentence[:missing.start()]
                if type(scope_version) is int and scope_version in (4,5,6,7):
                    # Nominal headings and attributive untested dimensions under
                    # a negative epistemic modal do not assert author omission.
                    if (not prefix.strip() and re.match(r'未验证范围\s*[:：]', sentence)):
                        continue
                    if scope_version in (5,6,7) and not prefix.strip() and sentence.strip()=='未验证范围':
                        continue
                    if (re.match(r'(?:未测试|未验证)(?:的)?(?:维度|场景|条件|范围)', sentence[missing.start():])
                            and re.search(r'(?:不能|不足以|尚不能)(?:证明|确认)[^，,；;]*$', prefix)):
                        continue
                papers = list(_PAPER.finditer(prefix))
                scopes = list(_SCOPED.finditer(prefix))
                if type(scope_version) is int and scope_version in (3,4,5,6,7):
                    subject=_CURRENT_EVIDENCE_SUBJECT.search(prefix)
                    if subject:
                        scopes.append(subject)
                if type(scope_version) is int and scope_version in (1,2,3,4,5,6,7):
                    # This guard concerns missing research/reporting, not the
                    # method's negative premises (e.g. an object absent from
                    # the initial frame). Those still require semantic review.
                    if missing.group() == '不存在' and not _PUBLICATION_OBJECT.search(sentence):
                        continue
                    if not papers and not _REPORTING_ABSENCE.search(missing.group()) \
                            and not _PUBLICATION_OBJECT.search(sentence):
                        continue
                # A proposal still asserts a fact when it says the paper omitted X.
                if not factual and not papers:
                    continue
                bounded = bool(scopes)
                if bounded and papers and papers[-1].start() > scopes[-1].start():
                    # "当前取得的论文片段" is bounded; "所选证据..., 但论文" is not.
                    bounded = bool(re.match(r'(?:的)?片段', prefix[papers[-1].end():]))
                if not bounded:
                    return True
    return False
