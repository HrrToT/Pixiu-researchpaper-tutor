"""Preserve Form text and repeated occurrences while avoiding repeated decoding."""
import io

import pytest
from PyPDF2 import PdfReader, PdfWriter
from PyPDF2._page import PageObject
from PyPDF2.generic import (
    ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject,
)

from services import deep_research_pdf_parser as parser


def document(*, repeat=4, graphic=False, leaf_content=None, second_page=False):
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'),
    }))

    def form(data, children=None):
        resources = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        if children:
            resources[NameObject('/XObject')] = DictionaryObject({NameObject(k): v for k, v in children.items()})
        value = DecodedStreamObject()
        value.set_data(data)
        value.update({NameObject('/Type'): NameObject('/XObject'),
                      NameObject('/Subtype'): NameObject('/Form'),
                      NameObject('/BBox'): ArrayObject([NumberObject(v) for v in (0, 0, 100, 100)]),
                      NameObject('/Resources'): resources})
        return writer._add_object(value)

    leaf = form(leaf_content or b'BT /F1 12 Tf 0 10 Td (evidence 42) Tj ET')
    children = {'/Child': leaf}
    stream = b'/Child Do\n' * repeat
    if graphic:
        # Pure paths have no text operators. Repeat inside and outside forms.
        children['/Shape'] = form(b'q\n' + b'0 0 m 1 1 l 2 0 l h S\n' * 50 + b'Q')
        stream += b'/Shape Do\n' * repeat
    branch = form(stream, children)
    top = form(b'/Branch Do\n' * repeat, {'/Branch': branch})

    def page(content, obj):
        writer.add_blank_page(width=100, height=100)
        value = writer.pages[-1]
        value[NameObject('/Resources')] = DictionaryObject({
            NameObject('/XObject'): DictionaryObject({NameObject('/Top'): obj}),
        })
        contents = DecodedStreamObject(); contents.set_data(content)
        value[NameObject('/Contents')] = writer._add_object(contents)
    page(b'/Top Do\n' * repeat, top)
    if second_page:
        page(b'/Top Do', form(b'BT /F1 12 Tf (different source 99) Tj ET'))
    output = io.BytesIO(); writer.write(output)
    return output.getvalue()


def test_nested_forms_keep_every_occurrence_and_decode_each_identity_once(monkeypatch):
    body = document()
    original = PageObject.extract_xform_text
    calls = []
    def counted(self, xform, *args, **kwargs):
        calls.append(id(xform))
        return original(self, xform, *args, **kwargs)
    monkeypatch.setattr(PageObject, 'extract_xform_text', counted)
    expected = PdfReader(io.BytesIO(body)).pages[0].extract_text()
    assert expected.count('evidence 42') == 64 and len(calls) == 84
    calls.clear()
    actual = parser._extract_page_text(PdfReader(io.BytesIO(body)).pages[0])
    assert actual == expected and len(calls) == 3


@pytest.mark.parametrize('content', [
    b'BT /F1 12 Tf (ordinary text) Tj ET',
    b"(quote-only text) '",
    b'0 0 (double-quote-only text) "',
])
def test_text_and_quote_operators_are_never_classified_as_pure_graphics(content):
    body = document(repeat=1, graphic=True, leaf_content=content)
    expected = PdfReader(io.BytesIO(body)).pages[0].extract_text()
    assert 'text' in expected
    assert parser._extract_page_text(PdfReader(io.BytesIO(body)).pages[0]) == expected


def test_parser_retains_page_identity_and_different_same_named_forms():
    body = document(repeat=2, graphic=True, second_page=True)
    expected = [{'page': i + 1, 'text': (p.extract_text() or '')[:30000]}
                for i, p in enumerate(PdfReader(io.BytesIO(body)).pages)]
    assert parser.parse_pdf(body, 2) == expected
    assert 'evidence 42' in expected[0]['text']
    assert 'different source 99' in expected[1]['text']
    with pytest.raises(ValueError): parser.parse_pdf(body, 1)


def test_form_hook_restored_after_page_failure():
    class Page:
        def extract_xform_text(self, *a, **kw): return 'unchanged'
        def extract_text(self): raise ValueError('fixture failure')
    page = Page(); original = page.extract_xform_text
    with pytest.raises(ValueError, match='fixture failure'): parser._extract_page_text(page)
    assert page.extract_xform_text == original


def test_visitors_bypass_cache_and_graphic_fast_path():
    callback = object(); calls = []
    class Form:
        def get_data(self): raise AssertionError('Visitor path must not inspect or skip form')
    form = Form()
    class Page:
        def extract_xform_text(self, *a, **kw): calls.append((a, kw)); return 'observed'
        def extract_text(self):
            return self.extract_xform_text(form, visitor_text=callback) + self.extract_xform_text(form, visitor_text=callback)
    assert parser._extract_page_text(Page()) == 'observedobserved'
    assert len(calls) == 2 and all(c[1].get('visitor_text') is callback or c[0][-1] is callback for c in calls)


@pytest.mark.parametrize('entries,bytes_limit,expected_calls', [(2, 64, 4), (8, 6, 5)])
def test_form_cache_obeys_both_entry_and_text_byte_limits(monkeypatch, entries, bytes_limit, expected_calls):
    monkeypatch.setattr(parser, 'FORM_CACHE_ENTRIES', entries)
    monkeypatch.setattr(parser, 'FORM_CACHE_BYTES', bytes_limit)
    calls = []
    class Form:
        def __init__(self, text): self.text = text
        def get_data(self): return b'BT'
    a, b, c = (Form(t) for t in ['aaaa', 'bbbb', 'cccc'])
    class Page:
        def extract_xform_text(self, form, *a): calls.append(form); return form.text
        def extract_text(self): return ''.join(self.extract_xform_text(f) for f in [a, b, a, c, b])
    assert parser._extract_page_text(Page()) == 'aaaabbbbaaaaccccbbbb'
    assert len(calls) == expected_calls
