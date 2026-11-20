"""Recognize explicit reader descriptions, never infer ability from paper data."""
import re

_READERS = re.compile(r'(?:面向|针对|适合|给|供|向)(?P<background>[^。！？；;\n]{1,96}?)'
                      r'(?:的人|的读者|读者|的同学|的学生|的听众)')
_UNFAMILIAR = re.compile(r'(?:没(?:有)?|未|尚未|还没)(?:读|看|接触|学|了解|深入)'
                         r'|(?:不|尚不|并不)熟悉|(?:只|仅)(?:了解|知道|学过|接触过)')
_EXPERT = re.compile(r'专家|资深|专业研究者|\b(?:experts?|advanced researchers?)\b',re.I)
_EXPLAIN = re.compile(r'解释|讲解|讲清楚|讲明白|介绍|说明|\b(?:explain|introduce|walk\s+through)\b',re.I)
_ENGLISH = re.compile(r'\b(?:for|to)\s+(?:readers|students|people|someone)\b'
    r'(?P<background>[^.!?;\n]{0,160}?(?:(?:have\s+not|haven\x27t|has\s+not|hasn\x27t|never|not\s+yet)'
    r'\s+(?:read|studied|seen|used)|(?:are\s+)?new\s+to\s+(?:this|the|these)))',re.I)


def enabled(record):
    return (type(record.get('audienceRequestContractVersion')) is int
            and record['audienceRequestContractVersion']==1
            and type(record.get('audienceRewriteContractVersion')) is int
            and record['audienceRewriteContractVersion']==9)


def described_reader_request(layer):
    """Admission hint only. Existing negatives, budget and evidence checks still apply."""
    if not isinstance(layer,str) or not _EXPLAIN.search(layer):return False
    for match in _READERS.finditer(layer):
        background=match['background']
        if _UNFAMILIAR.search(background) and not _EXPERT.search(background):return True
    return any(not _EXPERT.search(m['background']) for m in _ENGLISH.finditer(layer))
