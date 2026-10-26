"""Acquire exact PDF caption context for marked table variants; infer no aliases."""
import re


def enabled(record):
    return (type(record.get('tableIdentityContextContractVersion')) is int
            and record['tableIdentityContextContractVersion']==1)


GUIDANCE = '''
When reporting table cells, expose the exact dataset/group and method row label
in the same text as its metric/value. A human-readable method name may be followed
by the literal table label in parentheses; it must not replace that label.
Keep stars/variant suffixes literally (e.g. *), omitting only trailing bibliography
numbers. Read the supplied caption/note before calling a row original, re-trained,
fine-tuned or matched. Marker meaning is paper-specific; never guess it from *.
Original code/configurations does not imply original published measurements.
A separate caption source must be cited by that claim if it supplies baseline
provenance. It cannot verify cells outside the claim's own table quotations.
'''


def _body(row):
    return row.get('text','').split('Content:\n',1)[-1]


def include_context(rows,candidates,pdf_id,limit):
    """Use one bounded slot for exact caption prose, keeping its table source.

    Page, owner, index version and printed table number must all match. Only
    canonical PDF prose with an explicit note about marked variants qualifies.
    No source text/identity is rewritten and table geometry approval is not added.
    """
    if limit<2 or len(rows)>limit:return rows
    additions=[];protected=set()
    for table in rows:
        packet=table.get('tableData');meta=table.get('metadata') or {}
        methods=[r[1] for r in packet.get('rows',[]) if isinstance(r,list) and len(r)==3] if isinstance(packet,dict) else []
        markers={symbol for method in methods for symbol in ('*','∗','†','‡') if symbol in method}
        if not markers:continue
        number=re.match(r'^Table\s+(\d+[A-Za-z]?)\s*:',str((table.get('location') or {}).get('section','')),re.I)
        page=(table.get('location') or {}).get('page');version=meta.get('index_version')
        if (not number or type(page) is not int or not version or meta.get('id')!=pdf_id):continue
        caption=re.compile(r'\bTable\s+'+re.escape(number[1])+r'\s*:',re.I)
        matches=[]
        for candidate in candidates:
            cm=candidate.get('metadata') or {};text=_body(candidate)
            if (cm.get('id')!=pdf_id or cm.get('index_version')!=version
                    or (candidate.get('location') or {}).get('page')!=page
                    or cm.get('text_source')!='pdf_page_text' or cm.get('body_extraction_version')!=1
                    or candidate.get('tableData') or not caption.search(text)
                    or not any(symbol in text for symbol in markers|({'*','∗'} if markers&{'*','∗'} else set()))):continue
            # These terms select original note context; they assign no meaning.
            note=re.search(r'\b(?:marked|denot\w*|indicat\w*|re[-\s]?train\w*|fine[-\s]?tun\w*)\b',text,re.I)
            if note:matches.append(candidate)
        if matches:
            selected=max(matches,key=lambda c:len(_body(c)))
            protected.add(table['sourceId'])
            if selected['sourceId'] not in {r['sourceId'] for r in rows+additions}:
                additions.append(selected)
            else:protected.add(selected['sourceId'])
            break  # At most one context slot per acquisition call.
    if not additions:return rows
    result=list(rows)
    if len(result)==limit:
        # Keep every acquired table, including separate ablation/condition rows.
        removable=[i for i,r in enumerate(result) if i>0 and r['sourceId'] not in protected
                   and not r.get('tableData') and r.get('retrievalMode')=='indexed_hybrid']
        if not removable:return rows
        result.pop(removable[-1])
    return result+additions
