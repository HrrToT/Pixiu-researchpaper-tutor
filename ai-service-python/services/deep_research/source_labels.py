"""Readable source labels; document/version identities are left untouched."""
import re

_INTERNAL_NAME = re.compile(r'(?:[a-f0-9]{32,64}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})(?:\.pdf)?', re.I)


def source_display_title(*candidates):
    values = [value.strip() for value in candidates if isinstance(value, str) and value.strip()]
    return next((value for value in values if not _INTERNAL_NAME.fullmatch(value)),
                values[0] if values else '')
