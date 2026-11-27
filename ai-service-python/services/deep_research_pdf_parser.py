"""Isolated public-PDF parsing worker; parent enforces a process deadline."""
import io
import json
import re
import sys
from collections import OrderedDict

PdfReader = None  # Imported inside parse_pdf so startup failures receive a safe category.


def _control_count(text):
    from services.deep_research.text_quality import control_count
    return control_count(text)


FORM_CACHE_ENTRIES = 256
FORM_CACHE_BYTES = 2 * 1024 * 1024
_TEXT_SHOW_OPERATOR = re.compile(rb"""T[Jj]|['"]""")
_FONT_ENCODING_SLOT = re.compile(rb'(?m)^\s*dup\s+(\d{1,3})\s+/([A-Za-z0-9_.-]+)\s+put[ \t]*$')
_SHORT_ARROWS = {b'shortleftarrow': '←', b'shortrightarrow': '→'}


def _font_arrows(font):
    """Read named slots from the PDF's own embedded Type 1 encoding."""
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
    for code, name in _FONT_ENCODING_SLOT.findall(prefix):
        point = int(code)
        if point in slots:
            return {}  # Ambiguous embedded encoding.
        slots[point] = name
    return {point: _SHORT_ARROWS[name] for point, name in slots.items()
            if point < 32 and point not in (9, 10, 13) and name in _SHORT_ARROWS}


def _decode_font_arrows(page):
    original = []
    decoded = []
    fonts = {}

    def visit(text, _cm, _tm, font, _size):
        original.append(text)
        if _control_count(text):
            key = id(font)
            if key not in fonts:
                fonts[key] = (font, _font_arrows(font))
            text = text.translate(fonts[key][1])
        decoded.append(text)

    observed = page.extract_text(visitor_text=visit)
    if observed == ''.join(original):
        return ''.join(decoded)
    return ''


def _image_only_form(xform, data):
    if _TEXT_SHOW_OPERATOR.search(data):
        return False
    try:
        children = xform['/Resources']['/XObject']
        return bool(children) and all(children[name]['/Subtype'] == '/Image' for name in children)
    except (KeyError, TypeError, AttributeError):
        return False


def _extract_page_text(page):
    """Reuse Form text within this page without dropping repeated occurrences.

    A Form with no T-family operator, quote text operator, or Do invocation
    cannot contribute text or invoke a nested Form. A Form with only image
    children and no text-show operator cannot contribute text either. The raw-byte negative
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
        if isinstance(data, bytes) and (not any(mark in data for mark in (b'T', b"'", b'"', b'Do'))
                                        or _image_only_form(xform, data)):
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


def parse_pdf(body: bytes, max_pages: int, *, include_tables=False, include_named_tables=False,
              include_declared_arrows=False) -> list[dict]:
    reader_type = PdfReader
    if reader_type is None:
        from PyPDF2 import PdfReader as reader_type
    reader = reader_type(io.BytesIO(body))
    if reader.is_encrypted or len(reader.pages) > max_pages:
        raise ValueError("Unsupported PDF")
    modern = None
    pages = []
    for index, page in enumerate(reader.pages):
        text = _extract_page_text(page)[:30000]
        controls = _control_count(text)
        row = {"page": index + 1, "text": text}
        if controls:
            # Retry decoding the SAME bytes, not acquisition or generation.
            # The parent process deadline and original limits still apply.
            import pypdf
            if modern is None:
                modern = pypdf.PdfReader(io.BytesIO(body))
                if modern.is_encrypted or len(modern.pages) != len(reader.pages):
                    raise ValueError("Inconsistent PDF page identity")
            candidate = (modern.pages[index].extract_text() or "")[:30000]
            recovered_arrows = False
            if include_declared_arrows and _control_count(candidate):
                decoded = _decode_font_arrows(modern.pages[index])[:30000]
                if decoded.strip() and not _control_count(decoded):
                    candidate, recovered_arrows = decoded, True
            if candidate.strip() and not _control_count(candidate):
                row.update(text=candidate, extraction={"engine": "pypdf", "version": pypdf.__version__,
                    "reason": "unreadable_glyphs", "originalControlCount": controls})
                if recovered_arrows:
                    row['extraction']['encodingRecovery'] = 'embedded_type1_named_arrows'
            else:
                # Keep the exact original page, including an unreadable figure.
                # New-run evidence admission rejects affected source windows;
                # readable pages/windows remain available, never invented glyphs.
                row['extraction']={"engine":"PyPDF2","fallbackEngine":"pypdf",
                    "fallbackVersion":pypdf.__version__,"status":"unreadable_glyphs",
                    "originalControlCount":controls}
        if include_tables or include_named_tables:
            from core.pdf_repeated_metric_tables import verified_metric_tables
            from core.pdf_benchmark_columns import verified_percentage_tables, verified_ruled_two_tier_tables
            try:
                tables = verified_metric_tables(page, text) if include_tables else []
                if include_named_tables:
                    recognized = {table['number'] for table in tables}
                    tables.extend(table for table in verified_percentage_tables(page, text)
                                  if table['number'] not in recognized)
                    recognized = {table['number'] for table in tables}
                    tables.extend(table for table in verified_ruled_two_tier_tables(page, row['text'])
                                  if table['number'] not in recognized)
            except (KeyError, ValueError, TypeError, ImportError, AttributeError, UnboundLocalError):
                tables = []  # Optional geometry cannot make readable PDF prose unavailable.
            if tables:
                row['verifiedTables'] = tables
        pages.append(row)
    return pages


def main():
    try:
        max_pages, max_bytes = int(sys.argv[1]), int(sys.argv[2])
        if not 1 <= max_pages <= 100 or not 1 <= max_bytes <= 64 * 1024 * 1024:
            return 2
        body = sys.stdin.buffer.read(max_bytes + 1)
        if len(body) > max_bytes:
            return 2
        flags = sys.argv[3:]
        result = parse_pdf(body, max_pages, include_tables='--verified-tables' in flags,
                           include_named_tables='--verified-percentage-tables' in flags,
                           include_declared_arrows='--declared-font-arrows' in flags)
        sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        return 0
    except Exception as error:
        # Never forward document data or parser diagnostics into the UI/logs.
        from services.deep_research.pdf_worker_errors import encode_failure
        sys.stderr.write(encode_failure(error))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
