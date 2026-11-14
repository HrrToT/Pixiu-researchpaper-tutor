"""Publication revision from a byte-verified owned PDF header, never a filename."""
from copy import deepcopy
import re

_STAMP = re.compile(r'arXiv:\s*(\d{4}\.\d{4,5})\s*v\s*(\d+)\b', re.I)


def from_verified_pages(material, pages):
    first = [p for p in pages if p.get('page') == 1 and isinstance(p.get('text'),str)]
    if len(first) != 1:
        return None
    matches = list(_STAMP.finditer(first[0]['text']))
    if len(matches) != 1 or not material.get('contentHash'):
        return None
    m=matches[0]
    return {'scheme':'arxiv','workId':'arxiv:'+m[1],'revision':'v'+m[2],
            'displayId':'arxiv:'+m[1]+'v'+m[2], 'contentHash':material['contentHash'],
            'physicalPage':1,'literalStamp':m[0],'origin':'owned_pdf_header'}


def validated(value, content_hash):
    if not isinstance(value,dict) or not content_hash or value.get('contentHash') != content_hash:
        return None
    match = _STAMP.fullmatch(value.get('literalStamp','')) if isinstance(value.get('literalStamp'),str) else None
    if (not match or value.get('scheme') != 'arxiv' or value.get('origin') != 'owned_pdf_header'
            or type(value.get('physicalPage')) is not int or value['physicalPage'] != 1
            or value.get('workId') != 'arxiv:'+match[1] or value.get('revision') != 'v'+match[2]
            or value.get('displayId') != 'arxiv:'+match[1]+'v'+match[2]):
        return None
    return deepcopy(value)


GUIDANCE = '''publicationIdentity is a server-established publication/revision identity from the
owned PDF's literal first-page arXiv stamp after its snapshot byte hash was checked. It identifies
WHICH work/revision is cited; that revision need not be repeated in each body quotation. It is not
scientific support for a method, result or claim that another paper is absent from the task.
Do not infer a different/missing revision from a body quote without a version number. Preserve the
technical workId/versionId for ownership. Paper-specific facts still need their own cited body evidence.'''
