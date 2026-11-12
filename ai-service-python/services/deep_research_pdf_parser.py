"""Isolated public-PDF parsing worker; parent enforces a process deadline."""
import io
import json
import sys
from collections import OrderedDict

from PyPDF2 import PdfReader


FORM_CACHE_ENTRIES = 256
FORM_CACHE_BYTES = 2 * 1024 * 1024


def _extract_page_text(page):
    """Reuse Form text within this page without dropping repeated occurrences.

    A Form with no T-family operator, quote text operator, or Do invocation
    cannot contribute text or invoke a nested Form. The raw-byte negative
    filter is conservative: markers in comments/strings only cause extra work.
    Text-bearing or nested Forms still use the original extractor. Visitor
    calls bypass both optimizations so their observable callbacks are retained.
    """
    original = page.extract_xform_text
    cache = OrderedDict()
    used_bytes = 0

    def extract(xform, orientations=(0, 90, 270, 360), space_width=200.0,
                visitor_operand_before=None, visitor_operand_after=None, visitor_text=None):
        nonlocal used_bytes
        if any(v is not None for v in (visitor_operand_before, visitor_operand_after, visitor_text)):
            return original(xform, orientations, space_width, visitor_operand_before,
                            visitor_operand_after, visitor_text)
        key = (id(xform), tuple(orientations), space_width)
        if key in cache:
            cache.move_to_end(key)
            return cache[key][1]
        data = xform.get_data()
        if isinstance(data, bytes) and not any(mark in data for mark in (b'T', b"'", b'"', b'Do')):
            text = ''
        else:
            text = original(xform, orientations, space_width)
        size = len(text.encode('utf-8'))
        if size <= FORM_CACHE_BYTES:
            while cache and (len(cache) >= FORM_CACHE_ENTRIES or used_bytes + size > FORM_CACHE_BYTES):
                _, old = cache.popitem(last=False)
                used_bytes -= old[2]
            # Retain the object too, preventing Python id reuse within this page.
            cache[key] = (xform, text, size)
            used_bytes += size
        return text

    page.extract_xform_text = extract
    try:
        return page.extract_text() or ''
    finally:
        page.extract_xform_text = original
        cache.clear()


def parse_pdf(body: bytes, max_pages: int) -> list[dict]:
    reader = PdfReader(io.BytesIO(body))
    if reader.is_encrypted or len(reader.pages) > max_pages:
        raise ValueError("Unsupported PDF")
    return [{"page": index + 1, "text": _extract_page_text(page)[:30000]}
            for index, page in enumerate(reader.pages)]


def main():
    try:
        max_pages, max_bytes = int(sys.argv[1]), int(sys.argv[2])
        if not 1 <= max_pages <= 100 or not 1 <= max_bytes <= 64 * 1024 * 1024:
            return 2
        body = sys.stdin.buffer.read(max_bytes + 1)
        if len(body) > max_bytes:
            return 2
        result = parse_pdf(body, max_pages)
        sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        return 0
    except Exception:
        # Never forward document data or parser diagnostics into the UI/logs.
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
