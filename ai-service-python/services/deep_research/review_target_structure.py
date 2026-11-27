"""Bounded references to the target's structure are not paper measurements."""
import re

_SMALL={'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
_ENGLISH={w:i for i,w in enumerate(('one','two','three','four','five','six','seven','eight','nine','ten'),1)}
_REFERENCE=re.compile(r'(?P<cnlabel>最后|第|前|后)(?P<cnnumber>[0-9]{1,3}|[一二两三四五六七八九十]{1,3})(?:个)?(?P<cnunit>分句|句|段|条陈述|条断言)'
    r'|\b(?P<enlabel>first|last|final|next|previous)\s+(?P<ennumber>[0-9]{1,3}|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?P<enunit>clauses?|sentences?|paragraphs?)\b',re.I)
_SOURCE=re.compile(r'原文|论文|来源|引文|算法|表格|章节|\b(?:source|paper|passage|quote|algorithm|table|section|line|evidence|arxiv|doi)\b'
    r'|(?<![A-Za-z0-9_])(?:[EPQT]_*\d+|ev_[0-9a-f]+)(?![A-Za-z0-9_])',re.I)
_DEMONSTRATIVE = re.compile(r'[这那](?P<word>一)(?:条件|陈述|断言|分句)')
_NAMED_PAIR = re.compile(
    r'(?:^|(?<=[。！？\n]))\s*(?:这)?(?P<count>两|二|2)(?:种|项)(?P<kind>损失|指标|方法)'
    r'(?:(?:的)?(?:作用|约束作用|用途))?分别(?:由|是|为)'
    r'(?P<first>[\u4e00-\u9fffA-Za-z_-]{1,20}?(?P=kind))(?:描述|定义)?'
    r'(?:和|与|及|、)(?P<second>[\u4e00-\u9fffA-Za-z_-]{1,20}?(?P=kind))(?:描述|定义)?'
    r'(?:支持|说明)?(?=[。！？\n]|$)'
)
_TABLE_LOCATOR = re.compile(
    r'(?:^|(?<=[.!?。！？\n]))[ \t]*(?:The\s+)?tableBindings\s+(?:correctly\s+)?'
    r'(?:references?|points?\s+to)\s+(?P<alias>E[1-9]\d*)\s+rows?\s+'
    r'(?P<first>[1-9]\d{0,3})(?:\s+and\s+(?P<second>[1-9]\d{0,3}))?'
    r'(?=[ \t]*(?:[.!?。！？](?:\s|$)|\n|$))', re.I,
)
_ROW_COUNT = re.compile(
    r'(?<![0-9一二两三四五六七八九十])(?P<cn>[1-9]\d?|[一二两三四五六七八九十]{1,3})'
    r'\s*个(?:目标(?:表格)?行|表行(?=序关系|排序))'
    r'|\b(?P<en>[1-9]\d?|one|two|three|four|five|six|seven|eight|nine|ten)\s+target\s+table\s+rows?\b',
    re.I,
)


def _number(text):
    value=text.lower()
    if value.isascii() and value.isdigit():return int(value)
    if value in _ENGLISH:return _ENGLISH[value]
    if value in _SMALL:return _SMALL[value]
    if value.count('十')==1:
        a,b=value.split('十')
        if (not a or a in _SMALL and _SMALL[a]<10) and (not b or b in _SMALL and _SMALL[b]<10):
            return (_SMALL[a] if a else 1)*10+(_SMALL[b] if b else 0)
    return None


def _units(text,kind):
    if kind=='paragraphs':parts=re.split(r'\n+',text)
    elif kind=='sentences':parts=re.split(r'[。！？!?]+|\.(?=\s+[A-Z]|\s*$)',text)
    else:parts=re.split(r'[。！？!?；;，,：:\n]+|\.(?=\s+[A-Z]|\s*$)',text)
    return sum(bool(x.strip()) for x in parts)


def view(text,target_text, *, named_pairs=False):
    """Return numeric-scanning view plus provenance; never rewrite the verdict.

    Only explicit first/last/ordinal references to available target text units
    qualify. Paper/algorithm/line references, scientific counts and out-of-range
    indices remain numeric. The punctuation-based bound is navigation capacity,
    never semantic support or approval of the review's asserted facts.
    """
    if not isinstance(text,str) or not isinstance(target_text,str):return text,[]
    chars=list(text);references=[]
    for match in _DEMONSTRATIVE.finditer(text):
        chars[match.start('word')] = ' '
    if named_pairs:
        for match in _NAMED_PAIR.finditer(text):
            items = (match['first'], match['second'])
            if items[0] == items[1] or not all(item in target_text for item in items):
                continue
            start, end = match.span('count')
            chars[start:end] = ' ' * (end - start)
            references.append({'text':match.group().strip(), 'start':match.start(), 'end':match.end(),
                'kind':'named_target_pair', 'count':2, 'targetItems':list(items)})
    for m in _REFERENCE.finditer(text):
        # A colon introduces an excerpt owned by its source alias (E1: ...).
        # Keep that owner in scope, including full evidence hash identities.
        before=re.split(r'[。！？!?；;，,\n（）()]',text[:m.start()])[-1][-128:]
        after=text[m.end():m.end()+24]
        # Source-owned references are not target navigation. Do not mask a
        # source location even when its count coincides with target capacity.
        if _SOURCE.search(before) or re.match(r'(?:的)?(?:原文|论文|来源|引文)',after) or re.match(r'\s+(?:of|in)\s+(?:the\s+)?(?:paper|source|passage|quote|algorithm)\b',after,re.I):continue
        token=m.group('cnnumber') or m.group('ennumber');count=_number(token)
        unit=m.group('cnunit') or m.group('enunit').lower()
        kind='paragraphs' if unit=='段' or unit.startswith('paragraph') else 'sentences' if unit=='句' or unit.startswith('sentence') else 'clauses'
        available=_units(target_text,kind)
        if count is None or not 1<=count<=available:continue
        start,end=m.span('cnnumber' if m.group('cnnumber') else 'ennumber')
        chars[start:end]=' '*(end-start)
        references.append({'text':m.group(),'start':m.start(),'end':m.end(),'kind':kind,'count':count,'availableUnits':available})
    return ''.join(chars),references


def table_locator_view(text, claim, evidence, aliases):
    """Exclude row addresses from numeric scanning only for verified cell bindings."""
    from services.deep_research.table_bindings import bound_table_context

    bindings = claim.get('tableBindings')
    if not isinstance(bindings, list) or not bindings:
        return text, []
    chars = list(text)
    references = []
    for match in _TABLE_LOCATOR.finditer(text):
        evidence_id = aliases.get(match['alias'])
        if evidence_id not in evidence:
            continue
        slots = [slot for slot in ('first', 'second') if match[slot] is not None]
        row_numbers = [int(match[slot]) for slot in slots]
        bound_rows = {binding['rowNumber'] for binding in bindings if isinstance(binding, dict)
                      and binding.get('evidenceId') == evidence_id and type(binding.get('rowNumber')) is int
                      and bound_table_context({**claim, 'tableBindings': [binding]}, [evidence[evidence_id]])}
        if not set(row_numbers) <= bound_rows:
            continue
        for slot in slots:
            start, end = match.span(slot)
            chars[start:end] = ' ' * (end - start)
        references.append({'text': match.group(), 'start': match.start(), 'end': match.end(),
                           'kind': 'table_rows', 'evidenceId': evidence_id, 'rowNumbers': row_numbers})
    return ''.join(chars), references


def revision_row_count_view(text, bound_notes, numbers):
    """Recognize counts of explicitly reviewed table rows, across owned revisions."""
    matches = list(_ROW_COUNT.finditer(text))
    if not matches:
        return text, []
    from services.deep_research.publication_identity import validated
    from services.deep_research.table_evidence import visible_table_packet

    rows = set()
    for source, statement, excerpt in bound_notes:
        version = source.get('versionId')
        publication = validated(source.get('publicationIdentity'), version)
        table = (source.get('location') or {}).get('table')
        if (not publication or source.get('workId') != version + '.pdf' or not table
                or source.get('accessLevel') != 'fulltext'):
            continue
        packet = visible_table_packet(source.get('tableData'), excerpt)
        if not packet:
            continue
        stated_numbers = numbers(statement)
        for number, label, values in packet['rows']:
            if (label.strip() and re.search(r'(?<![A-Za-z0-9_.-])' + re.escape(label) + r'(?![A-Za-z0-9_.-])', statement, re.I)
                    and len(stated_numbers & numbers(' '.join(values))) >= 2):
                rows.add((publication['workId'], publication['revision'], table, number))
    revisions = {row[1] for row in rows}
    if (len({row[0] for row in rows}) != 1 or len(revisions) < 2
            or len({(row[1], row[2]) for row in rows}) != len(revisions)):
        return text, []
    chars = list(text)
    references = []
    for match in matches:
        key = 'cn' if match['cn'] is not None else 'en'
        if _number(match[key]) == len(rows):
            start, end = match.span(key)
            chars[start:end] = ' ' * (end - start)
            references.append({'text': match.group(), 'start': match.start(), 'end': match.end(),
                               'kind': 'referenced_revision_rows', 'rows': sorted(rows)})
    return ''.join(chars), references
