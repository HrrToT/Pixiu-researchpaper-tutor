"""Recover encoded glyphs from the PDF's embedded font; never infer a symbol."""
import io
from unittest.mock import Mock
import pytest
from PyPDF2 import PdfReader,PdfWriter
from PyPDF2.generic import DictionaryObject,NameObject,DecodedStreamObject,NumberObject
from services import deep_research_pdf_parser as parser


def font_document(glyph='beta',embedded=True,normal=False,declared_arrows=False):
    writer=PdfWriter();writer.add_blank_page(300,300)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/FixtureFont')})
    if embedded:
        prefix=b'%!PS-AdobeFont-1.0\n/Encoding 256 array\ndup 12 /'+glyph.encode()+b' put\nreadonly def\neexec\n'
        stream=DecodedStreamObject();stream.set_data(prefix)
        if declared_arrows:
            stream[NameObject('/Length1')]=NumberObject(len(prefix))
        descriptor=DictionaryObject({NameObject('/Type'):NameObject('/FontDescriptor'),NameObject('/FontName'):NameObject('/FixtureFont'),NameObject('/FontFile'):writer._add_object(stream)})
        font[NameObject('/FontDescriptor')]=writer._add_object(descriptor)
    writer.pages[0][NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    contents=DecodedStreamObject();contents.set_data(b'BT /F1 12 Tf 20 20 Td '+(b'(ordinary source 42)' if normal else b'(\\014)')+b' Tj ET')
    writer.pages[0][NameObject('/Contents')]=writer._add_object(contents)
    output=io.BytesIO();writer.write(output);return output.getvalue()


@pytest.mark.parametrize('name,symbol',[('beta','β'),('alpha','α'),('minus','−')])
def test_symbol_comes_from_each_documents_own_font_encoding(name,symbol):
    body=font_document(name)
    assert PdfReader(io.BytesIO(body)).pages[0].extract_text()=='\x0c'
    result=parser.parse_pdf(body,1)
    assert result[0]['text']==symbol
    assert result[0]['page']==1 and result[0]['extraction']=={'engine':'pypdf','version':'6.21.4','reason':'unreadable_glyphs','originalControlCount':1}


def test_readable_original_text_keeps_exact_page_schema_and_never_loads_fallback(monkeypatch):
    import pypdf
    body=font_document(normal=True)
    expected=PdfReader(io.BytesIO(body)).pages[0].extract_text()
    monkeypatch.setattr(pypdf,'PdfReader',Mock(side_effect=AssertionError('No fallback for readable text')))
    assert parser.parse_pdf(body,1)==[{'page':1,'text':expected}]


def test_unknown_glyph_is_not_stripped_or_replaced_with_a_guessed_symbol():
    page=parser.parse_pdf(font_document(embedded=False),1)[0]
    assert page['text']=='\x0c' and page['extraction']['status']=='unreadable_glyphs'


@pytest.mark.parametrize(('name','arrow'), [('shortleftarrow','←'),('shortrightarrow','→')])
def test_exact_named_embedded_font_arrows_recover_without_changing_legacy_pdf_parse(name,arrow):
    body=font_document(name,declared_arrows=True)
    legacy,=parser.parse_pdf(body,1)
    fresh,=parser.parse_pdf(body,1,include_declared_arrows=True)
    assert legacy['text']=='\x0c' and legacy['extraction']['status']=='unreadable_glyphs'
    assert fresh['text']==arrow and fresh['page']==legacy['page']==1
    assert fresh['extraction']['encodingRecovery']=='embedded_type1_named_arrows'


def test_unknown_font_mapping_remains_unreadable_with_arrow_recovery_enabled():
    for body in (font_document('unknownarrow',declared_arrows=True),font_document(embedded=False)):
        page,=parser.parse_pdf(body,1,include_declared_arrows=True)
        assert page['text']=='\x0c' and page['extraction']['status']=='unreadable_glyphs'


def test_fallback_uses_same_pdf_bytes_and_page_identity(monkeypatch):
    import pypdf
    body=font_document();seen=[];actual=pypdf.PdfReader
    def reader(stream):
        seen.append(stream.getvalue());return actual(stream)
    monkeypatch.setattr(pypdf,'PdfReader',reader)
    assert parser.parse_pdf(body,1)[0]['text']=='β' and seen==[body]
    with pytest.raises(ValueError):parser.parse_pdf(body,0)


def test_fallback_rejects_changed_page_count(monkeypatch):
    import pypdf
    monkeypatch.setattr(pypdf,'PdfReader',lambda _:Mock(is_encrypted=False,pages=[]))
    with pytest.raises(ValueError,match='page identity'):parser.parse_pdf(font_document(),1)
