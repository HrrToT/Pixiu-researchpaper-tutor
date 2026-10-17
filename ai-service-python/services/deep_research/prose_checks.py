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
_ALIAS = re.compile(r'(?<![A-Za-z0-9_])(?:E|P)[1-9]\d*(?![A-Za-z0-9_])')
_RAW_ID = re.compile(r'(?<![A-Za-z0-9_])ev_[0-9a-f]{64}(?![A-Za-z0-9_])')


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


def leaks_internal_reference(claim, support):
    for text in claim_prose(claim):
        if _RAW_ID.search(text):
            return True
        for match in _ALIAS.finditer(text):
            alias = match.group()
            # A genuine paper symbol (e.g. E1 in an equation) retains its name.
            # Evidence aliases in a citation context never become public symbols.
            contextual = bool(re.search(r'(?:证据|来源|引文|根据)\s*$', text[:match.start()])
                              or re.match(r'\s*(?:表\s*\d|片段|来源|第\s*\d+\s*页)', text[match.end():]))
            token = re.compile(r'(?<![A-Za-z0-9_])' + re.escape(alias) + r'(?![A-Za-z0-9_])')
            if contextual or not any(token.search(item.get('quote', '')) for item in support):
                return True
    return False


def absence_not_established(claim, support):
    explicit = any(EXPLICIT_ABSENCE.search(item.get('quote', '')) for item in support)
    if explicit:
        return False  # Independent semantic verification still checks the exact subject/scope.
    factual = claim.get('kind') in {'reported', 'inference'}
    for text in claim_prose(claim):
        for sentence in re.split(r'[。！？；;.!?\n]', text):
            for missing in ABSENCE.finditer(sentence):
                prefix = sentence[:missing.start()]
                papers = list(_PAPER.finditer(prefix))
                scopes = list(_SCOPED.finditer(prefix))
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
