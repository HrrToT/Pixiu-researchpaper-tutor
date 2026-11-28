"""Glyph names declared by an embedded Type 1 font."""
import re

_ENCODING_SLOT = re.compile(rb'(?m)^\s*dup\s+(\d{1,3})\s+/([A-Za-z0-9_.-]+)\s+put[ \t]*$')


def declared_slots(font):
    try:
        if (not font or font.get('/Subtype') != '/Type1' or '/ToUnicode' in font or '/Encoding' in font):
            return {}
        stream = font['/FontDescriptor'].get_object()['/FontFile'].get_object()
        size = stream.get('/Length1')
        if not isinstance(size, int) or not 1 <= size <= 16384:
            return {}
        prefix = stream.get_data()[:size]
    except (KeyError, AttributeError, TypeError, ValueError):
        return {}
    if not prefix.startswith(b'%!') or b'/Encoding 256 array' not in prefix:
        return {}
    slots = {}
    for code, name in _ENCODING_SLOT.findall(prefix):
        point = int(code)
        if point > 255 or point in slots:
            return {}
        slots[point] = name
    return slots
