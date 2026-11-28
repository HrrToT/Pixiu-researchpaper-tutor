"""Readable source labels; document/version identities are left untouched."""
import re

_INTERNAL_NAME = re.compile(r'(?:[a-f0-9]{32,64}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})(?:\.pdf)?', re.I)
_VENUE_YEAR = re.compile(
    r'(?<![\w])(?:CVPR|ICCV|ECCV|WACV|NeurIPS|ICML|ICLR|ACL|EMNLP|NAACL|AAAI|IJCAI|SIGGRAPH)'
    r'\s+(?:19|20)\d{2}(?![A-Za-z0-9])', re.I)


def source_display_title(*candidates):
    values = [value.strip() for value in candidates if isinstance(value, str) and value.strip()]
    return next((value for value in values if not _INTERNAL_NAME.fullmatch(value)),
                values[0] if values else '')


def without_cited_edition(text, source_title):
    """Mask known venue-year editions only in an explicit citation form."""
    if not isinstance(source_title, str):
        return text
    for label in _VENUE_YEAR.findall(source_title):
        words = r'\s+'.join(map(re.escape, label.split()))
        text = re.sub(r'(?<![A-Za-z0-9_])' + words + r'(?=\s*(?:会议)?版|\s+edition\b)',
                      ' ', text, flags=re.I)
    return text
