"""Separate a checked prose-list length from empirical source quantities.

Only the displayed list count is handled here. The identity, completeness and
scientific meaning of every listed item still require semantic verification.
"""
import re

_LABEL = re.compile(
    r'(?<![A-Za-z0-9第负正+＋\-−零一二两三四五六七八九十百千万亿])'
    r'(?P<number>十二|十一|[二两三四五六七八九十]|1[0-2]|[2-9])'
    r'(?:个|项)(?:主要|关键|核心)?(?:环节|方面|部分|要点)'
    r'(?:分别(?:改变|是|为|包括)?|如下|包括)?[：:]')
_EXACT = re.compile(r'只有|仅|唯一|恰好|正好|总共|共|至少|至多|最多|最少|不超过|超过|固定|必须|负|正|[+＋\-−]|至|到|约')
_VALUES = dict(zip('二两三四五六七八九十', (2,2,3,4,5,6,7,8,9,10)))


def _balanced_items(body):
    pairs={'(':')','（':'）','[':']','【':'】','{':'}'}
    stack=[];items=[];start=0
    for i,char in enumerate(body):
        if char in pairs:
            stack.append(pairs[char])
        elif char in pairs.values():
            if not stack or stack.pop()!=char:return None
        elif char in ';；':
            if stack:return None  # Nested lists remain ambiguous.
            items.append(body[start:i]);start=i+1
    return None if stack else [*items,body[start:]]


def _numbered_items(body,count):
    """Recognize a complete 1..N sequence only at sibling item starts."""
    parts=re.split(r'[;；]',body)
    if len(parts)!=count:return None
    marker=re.compile(r'\s*(?:(?P<open>[（(])(?P<wrapped>\d{1,2})[）)]|(?P<bare>\d{1,2})[）)])')
    matches=[marker.match(part) for part in parts]
    if not any(matches):return body,[]
    if not all(matches):return None
    cleaned=[];spans=[];offset=0;style=None
    for number,(part,match) in enumerate(zip(parts,matches),1):
        if int(match['wrapped'] or match['bare'])!=number:return None
        token=match.group().strip()
        if match['open'] and not token.endswith({'(' : ')','（':'）'}[match['open']]):return None
        current=re.sub(r'\d+','#',token)
        if style is not None and style!=current:return None
        style=current
        cleaned.append(part[match.end():])
        spans.append((offset+match.start(),offset+match.end()))
        offset+=len(part)+1
    return '；'.join(cleaned),spans


def without_enumeration_labels(text,*,balanced_parentheses=False,numbered_items=False):
    """Ignore a matching list label, never a measured count or explicit total.

    Require a colon and exactly N nonempty semicolon-separated items in one
    sentence. Missing items, nested lists and exact/exclusive quantifiers stay
    in the quantity gate. No original citation or published text is rewritten.
    """
    spans=[]
    for match in _LABEL.finditer(text):
        prefix=re.split(r'[。！？\n；;]',text[:match.start()])[-1]
        if _EXACT.search(prefix):
            continue
        body=re.split(r'[。！？\n]',text[match.end():],maxsplit=1)[0]
        word=match['number']
        count=int(word) if word.isdigit() else {'十一':11,'十二':12}.get(word,_VALUES.get(word))
        markers=[]
        if numbered_items:
            parsed=_numbered_items(body,count)
            if parsed is None:continue
            body,markers=parsed
        # Conservative: don't treat nested punctuation as sibling items.
        if balanced_parentheses:
            items=_balanced_items(body)
            if items is None:continue
        else:
            if any(c in body for c in '()（）[]【】{}'):
                continue
            items=re.split(r'[；;]',body)
        if (len(items)!=count or any(not item.strip() for item in items)
                or any(re.search(r'例如|比如|等(?:等)?\s*$|\.\.\.|…',item) for item in items)):
            continue
        spans.append(match.span('number'))
        spans.extend((match.end()+a,match.end()+b) for a,b in markers)
    return ''.join(c for i,c in enumerate(text) if not any(a<=i<b for a,b in spans))
