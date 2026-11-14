"""Page-faithful body text with verified printed heading hints and TEI supplements."""
from copy import deepcopy
import re
import unicodedata

from core.pdf_evidence_pages import extract_evidence_pages

FRONT_MATTER = 'Front Matter (Metadata)'


def _key(text):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(text))).casefold()


def _hints(sections):
    hints = []
    for section in sections:
        title = str(section.get('section') or '').strip()
        if (not title or title in (FRONT_MATTER,'unknown','Body Text')
                or section.get('evidenceKind') in ('table','formula')):
            continue
        number = str(section.get('headingNumber') or '')
        keys = {_key(title),_key(number+' '+title)}
        # Match the actual printed line, including its number when available.
        hints.append((keys,section))
    # These titles are used only if literally printed as a complete line.
    hints += [({_key(title)}, {'section':title}) for title in ('Abstract','References','Appendix')]
    return hints


def _heading_at(lines, offset, page_index, hints):
    for width in (1,2,3):
        if offset+width > len(lines): break
        candidate = ''.join(lines[offset:offset+width]).strip()
        if not candidate or len(candidate)>240: continue
        key = _key(candidate)
        matches = []
        for keys,section in hints:
            page = section.get('pageIndex')
            if key in keys and (page is None or page==page_index): matches.append(section)
        if matches:
            return matches[0],width
    return None,0


def build_pdf_source_sections(sections, pdf_path):
    """Replace potentially incomplete TEI prose, not structure or table identities.

    All nonblank page text remains in original order; splits never cross pages.
    Unreadable PDF text raises before indexing rather than silently reusing TEI.
    """
    pages = extract_evidence_pages(pdf_path)
    if not pages:
        raise ValueError('PDF contains no extractable body text; canonical text cannot be indexed')
    original = deepcopy(sections)
    hints = _hints(original)
    active = {'section':'Document opening'}
    body = []
    for page in pages:
        text = page['content'];index = page['pageIndex']
        lines = text.splitlines(keepends=True)
        boundaries = [];offset=0;skip_until=0
        for i,line in enumerate(lines):
            if i >= skip_until:
                heading,width = _heading_at(lines,i,index,hints)
                if heading is not None:
                    boundaries.append((offset,heading));skip_until=i+width
            offset += len(line)
        start=0;part=0
        for end,heading in [*boundaries,(len(text),None)]:
            if end>start and text[start:end].strip():
                part+=1
                item={'id':f'pdf-page-{index+1}-span-{part}', 'section':active['section'],
                    'content':text[start:end], 'pageIndex':index,'page':index+1,
                    'bodyExtractionVersion':1,'textSource':'pdf_page_text',
                    'pdfTextStart':start,'pdfTextEnd':end}
                for field in ('level','nestedLevel','headingNumber'):
                    if field in active:item[field]=active[field]
                body.append(item)
            if heading is not None:active=heading
            start=end
    # Keep synthetic metadata outside the evidence index as before.
    metadata=[s for s in original if s.get('section')==FRONT_MATTER]
    supplements=[s for s in original if s.get('evidenceKind') in ('table','formula')]
    return metadata+body+supplements
