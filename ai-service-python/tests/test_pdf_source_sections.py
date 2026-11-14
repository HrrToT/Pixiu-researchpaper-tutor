"""Complete body text and physical pages must survive imperfect TEI parsing."""
from copy import deepcopy
from unittest.mock import patch
import re
import pytest

from core.pdf_source_sections import build_pdf_source_sections
from core.smart_chunker import chunk_sections,normalize_section_titles


def pages():
    return [
        {'pageIndex':0,'content':'Paper title\nAbstract\nAbstract facts.\n1 Introduction\nFirst paragraph.\n'},
        {'pageIndex':1,'content':'Missing middle paragraph with camera geometry and training operations.\n'
            'Final summary.\n2 Related Works\nOther methods.\n'},
        {'pageIndex':3,'content':'3.1 Long Method\nHeading\nA complete equation is written here.\n'},
    ]


def hints():
    return [
        {'section':'Front Matter (Metadata)','content':'Title: synthetic metadata'},
        {'id':'intro','section':'Introduction','headingNumber':'1','pageIndex':0,'content':'First paragraph. Final summary.'},
        {'id':'related','section':'Related Works','headingNumber':'2','pageIndex':1,'content':'Other methods.'},
        {'id':'method','section':'Long Method Heading','headingNumber':'3.1','pageIndex':3,'content':'Equation: x=y'},
    ]


def test_recovers_dropped_paragraph_without_fake_tei_prose_or_losing_semantic_headings():
    supplied=hints();supplied[1]['content']+=' A TEI-only invented sentence.'
    before=deepcopy(supplied);actual=pages()
    with patch('core.pdf_source_sections.extract_evidence_pages',return_value=actual):
        result=build_pdf_source_sections(supplied,'paper.pdf')
    body=[s for s in result if s.get('textSource')=='pdf_page_text']
    for page in actual:
        recovered=''.join(s['content'] for s in body if s['pageIndex']==page['pageIndex'])
        assert recovered==page['content']
    assert next(s for s in body if 'Missing middle' in s['content'])['section']=='Introduction'
    assert next(s for s in body if 'Other methods' in s['content'])['section']=='Related Works'
    assert next(s for s in body if 'complete equation' in s['content'])['section']=='Long Method Heading'
    assert 'TEI-only invented' not in ''.join(s['content'] for s in result)
    assert supplied==before and len({s['id'] for s in body})==len(body)
    chunks=chunk_sections(normalize_section_titles(result))
    missing=next(c for c in chunks if 'Missing middle' in c['text'])
    assert missing['page']==2 and missing['pageIndex']==1
    assert missing['bodyExtractionVersion']==1 and missing['textSource']=='pdf_page_text'
    assert 'synthetic metadata' not in ''.join(c['text'] for c in chunks)
    assert not any('First paragraph' in c['text'] and 'Missing middle' in c['text'] for c in chunks)


def test_headings_must_be_printed_and_page_hint_cannot_move_them_to_another_page():
    source=[{'pageIndex':0,'content':'3 Results\nReal contents.'}]
    supplied=[{'section':'Results','headingNumber':'3','pageIndex':1,'content':'Wrong-page hint.'},
              {'section':'Invented conclusion','pageIndex':0,'content':'invented'}]
    with patch('core.pdf_source_sections.extract_evidence_pages',return_value=source):
        result=build_pdf_source_sections(supplied,'paper.pdf')
    assert [s['section'] for s in result]==['Document opening']
    assert result[0]['content']==source[0]['content']


def test_table_cell_identities_and_formula_supplements_are_kept_without_claiming_page_text_verified_them():
    supplied=hints()+[{'id':'t','section':'Table 1','evidenceKind':'table','content':'Table row 1: Ours | 1',
        'pageIndex':1,'tableVerifiedData':{'groups':[['Dataset',['SSIM']]],'rows':[[1,'Ours',['1']]]}},
        {'id':'eq','section':'Long Method Heading','evidenceKind':'formula','textSource':'grobid_formula',
         'content':'Equation: x=y'}]
    before=deepcopy(supplied)
    with patch('core.pdf_source_sections.extract_evidence_pages',return_value=pages()):
        result=build_pdf_source_sections(supplied,'paper.pdf')
    assert result[-2:]==supplied[-2:] and supplied==before
    body=[s for s in result if s.get('textSource')=='pdf_page_text']
    assert all('tableVerifiedData' not in s and s.get('evidenceKind')!='table' for s in body)
    assert 'pageIndex' not in result[-1]


def test_empty_pdf_text_is_not_silently_replaced_with_incomplete_tei():
    with patch('core.pdf_source_sections.extract_evidence_pages',return_value=[]):
        with pytest.raises(ValueError,match='no extractable body text'):
            build_pdf_source_sections(hints(),'paper.pdf')


def _write_pdf(path):
    from PyPDF2 import PdfWriter
    from PyPDF2.generic import NameObject,DictionaryObject,DecodedStreamObject
    writer=PdfWriter()
    for lines in (['1 Introduction','First paragraph.'],
                  ['Dropped middle paragraph about camera operations.','Final summary.']):
        writer.add_blank_page(width=612,height=792)
        page=writer.pages[-1]
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),
                               NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
        stream=DecodedStreamObject();stream.set_data(('BT /F1 12 Tf 20 740 Td '+
            ' '.join(('0 -18 Td ' if i else '')+'('+line+') Tj' for i,line in enumerate(lines))+' ET').encode())
        page[NameObject('/Contents')]=writer._add_object(stream)
    with path.open('wb') as f:writer.write(f)


def test_real_pdf_and_tei_parser_recover_middle_and_keep_equation_as_unpaged_supplement(tmp_path):
    from core.document_parser import parse_tei_xml
    pdf=tmp_path/'paper.pdf';_write_pdf(pdf)
    xml=tmp_path/'paper.tei.xml'
    xml.write_text('<TEI><text><body><div><head n="1" coords="1,1,1,10,10">Introduction</head>'
        '<p>First paragraph. Final summary.</p><formula>x=y</formula></div></body></text></TEI>',encoding='utf-8')
    legacy=parse_tei_xml(str(xml));result=parse_tei_xml(str(xml),str(pdf))
    assert 'Dropped middle' not in ''.join(s['content'] for s in legacy)
    body=[s for s in result if s.get('textSource')=='pdf_page_text']
    assert 'Dropped middle' in body[-1]['content'] and body[-1]['page']==2
    assert body[-1]['section']=='Introduction'
    formulas=[s for s in result if s.get('evidenceKind')=='formula']
    assert formulas[0]['content']=='Equation: x=y' and 'pageIndex' not in formulas[0]
    assert not any(s['content']=='First paragraph. Final summary.\nEquation: x=y' for s in result)
