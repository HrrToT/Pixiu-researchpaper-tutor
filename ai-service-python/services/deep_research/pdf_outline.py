"""Conservative IEEE outline hints; returned titles and source offsets stay literal."""
import re

_ROMAN = re.compile(r'(?m)^[ \t]*(?P<number>XX|XIX|XVIII|XVII|XVI|XV|XIV|XIII|XII|XI|IX|VIII|VII|VI|IV|III|II|X|V|I)\.[ \t]+(?P<title>[A-Z][^\n]{1,160})$')
_LETTER = re.compile(r'(?m)^[ \t]*(?P<number>[A-Z])\.[ \t]+(?P<title>[A-Z][^\n]{1,160})$')


def normalized_title(title):
    # PDF small capitals may become "M ETHOD". This view is never source text.
    return re.sub(r'\b([A-Z])[ \t]+([A-Z]{2,})\b',r'\1\2',title)


def events(text):
    rows=[];occupied=set()
    for pattern,prefix in ((_ROMAN,'R:'),(_LETTER,'L:')):
        for match in pattern.finditer(text):
            title=match['title'].strip()
            if (match.start() in occupied or len(title.split())>15
                    or re.search(r'[=≤≥∑Σ]|[.!?][ \t]',title)):
                continue
            rows.append((match.start(),prefix+match['number'],match['number']+'. '+title))
            occupied.add(match.start())
    return rows
