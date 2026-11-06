"""Literal PDF section boundaries for reading selection, never support verdicts."""
import re

_HEADING = re.compile(r'(?m)^[ \t]*(?P<number>\d{1,2}(?:\.\d{1,2}){0,4})[ \t]+(?P<title>[A-Za-z][^\n]{1,160})')
_REFERENCES = re.compile(r'(?m)^[ \t]*(?:REFERENCES|BIBLIOGRAPHY|参考文献)[ \t]*$')
_METHOD = re.compile(r'\b(?:method(?:s|ology)?|approach|algorithm|implementation|loss functions?|training procedure|optimization)\b',re.I)
_OTHER = re.compile(r'\b(?:introduction|related work|background|references|bibliography|conclusion|experiment|evaluation|results?|datasets?|baselines?|comparison|appendix)\b',re.I)
_ASK = re.compile(r'解释|如何|怎样|怎么|为什么|机制|原理|流程|方法|\b(?:explain|how|why|mechanism|procedure)\b',re.I)
_BACKGROUND = re.compile(r'相关工作|背景方法|以往方法|传统方法|\b(?:related work|prior methods?|previous methods?|traditional methods?)\b',re.I)
_RESULTS = re.compile(r'报告.*结果|实验结果|评测结果|性能结果|性能比较|数据集表现|\b(?:benchmark|results? comparison|reported results?|evaluation results?)\b',re.I)


def method_requested(question, *, outline=False):
    return bool((_ASK.search(question) or outline and re.search(r'表示|表征|参数化|提取路径|重建路径|\b(?:representation|parameterization|mesh extraction)\b',question,re.I))
                and not _BACKGROUND.search(question) and not _RESULTS.search(question))


def enabled(record):
    return type(record.get('externalReadingContractVersion')) is int and record['externalReadingContractVersion'] in (1,2)


def spans(pages, *, outline=False):
    """Keep page text/offsets; inherit numbered section paths across pages.

    This is conservative layout metadata. It neither attributes every sentence
    in a method section to its authors nor treats headings as scientific proof.
    """
    if type(outline) is not bool:raise ValueError("Invalid PDF outline policy")
    stack=[];result=[]
    for page in pages:
        text=page.get('text','');events=[]
        for m in _HEADING.finditer(text):
            title=m['title'].split('. ',1)[0].strip()
            # Tables, numbered prose and mathematical rows must not become a
            # section merely because they start with a number.
            if not title or len(title.split())>15 or not ('.' in m['number'] or _METHOD.match(title) or _OTHER.match(title)):
                continue
            events.append((m.start(),m['number'],m['number']+' '+title))
        if outline:
            from services.deep_research.pdf_outline import events as outline_events
            events.extend(outline_events(text))
        events.extend((m.start(),None,m.group().strip()) for m in _REFERENCES.finditer(text))
        start=0;parts=[]
        for offset,number,title in sorted(events):
            if offset>start:parts.append(_part(start,offset,stack))
            if number is None:stack=[('',title,'references')]
            else:
                if outline and number.startswith('L:'):
                    root=next((entry[0] for entry in stack if entry[0].startswith('R:') and '.' not in entry[0]),None)
                    if root:number=root+'.'+number[2:]
                level=number.count('.')+1
                stack=[entry for entry in stack if entry[0] and entry[0].count('.')+1<level
                       and number.startswith(entry[0]+'.')]
                role_title=title
                if outline:
                    from services.deep_research.pdf_outline import normalized_title
                    role_title=normalized_title(title)
                role='method' if _METHOD.search(role_title) else 'other' if (_OTHER.search(role_title)
                    or outline and re.search(r'\b(?:preliminar\w*|experiments|evaluations)\b',role_title,re.I)) else (stack[-1][2] if stack else 'unknown')
                stack.append((number,title,role))
            start=offset
        if start<len(text):parts.append(_part(start,len(text),stack))
        result.append((page,parts))
    return result


def _part(start,end,stack):
    return {'start':start,'end':end,'section':' / '.join(entry[1] for entry in stack),
            'role':stack[-1][2] if stack else 'unknown'}


def select(pages,query,terms,*,seen=(),contract_version=1):
    if type(contract_version) is not int or contract_version not in (1,2):raise ValueError("Invalid external reading policy")
    annotated=spans(pages,outline=contract_version==2);method_request=method_requested(query,outline=contract_version==2)
    def score(pair):
        page,parts=pair
        body=' '.join(page['text'][p['start']:p['end']] for p in parts if p['role']=='method')
        content=body if method_request and body.strip() else page.get('text','')
        counts=[content.lower().count(word) for word in terms]
        return (-(bool(body.strip()) if method_request else False),page.get('page') in seen,
                -sum(c>0 for c in counts),-sum(min(c,3) for c in counts))
    ranked=sorted((pair for pair in annotated if pair[0].get('text','').strip()),key=score)
    selected=ranked[:3]
    # A conceptual explanation also needs the author's overview, which can
    # establish what the proposed representation actually is. Keep two method
    # pages plus the first front-matter/introduction page, within the same cap.
    # Explicit derivations retain all three topic-ranked method pages.
    if method_request and not re.search(r'推导|公式|证明|\b(?:deriv\w*|equation|proof)\b',query,re.I):
        overview=next((pair for pair in annotated if pair[0].get('text','').strip()
                       and pair[1] and pair[1][0]['role']=='unknown'),None)
        methods=[pair for pair in ranked if any(p['role']=='method' for p in pair[1])]
        if overview is not None and methods:
            selected=methods[:2]+([overview] if all(pair[0] is not overview[0] for pair in methods[:2]) else [])
            selected+= [pair for pair in ranked if all(pair[0] is not p[0] for p in selected)][:3-len(selected)]
    return selected


def passages(page,parts,split):
    """Split at actual headings; offsets always refer to the original page."""
    text=page['text'];limit=min(len(text),6000)
    for part in parts:
        start,end=part['start'],min(part['end'],limit)
        if start>=end:continue
        for local,quote in split(text[start:end]):
            yield start+local,quote,part['section'],part['role']


def premise_priority(row,requirement,query):
    """Rank own-method premises; the final semantic check still owns support."""
    if row.get('sourceKind')!='arxiv' or not method_requested(requirement):return (0,0,0)
    text=row.get('quote','');location=row.get('location',{});section=location.get('section','')
    background=bool(re.search(r'related work|background|references|bibliography',section,re.I))
    method=location.get('sectionRole')=='method'
    why=bool(re.search(r'为什么|为何|\bwhy\b',requirement,re.I))
    identity=bool(re.search(r'是否|有没有|\b(?:whether|does)\b',requirement,re.I))
    operation=bool(re.search(r'怎样|怎么|如何|\bhow\b',requirement,re.I))
    if identity:
        own=bool(re.search(r'\b(?:we|our|this work)\b|本文|我们',text,re.I))
        definition=bool(re.search(r'\b(?:represent\w*|primitives?|retain\w*|reformulat\w*|keep\w*)\b',text,re.I))
        relation=int(own)+int(own and definition)
        kind=int(own and not method)
    elif why:
        relation=bool(re.search(r'\b(?:cannot|only|because|encourag\w*|enforc\w*|penaliz\w*|require\w*|supervision)\b',text,re.I))
        kind=int(method)
    elif operation:
        relation=sum(bool(re.search(r'\b'+verb+r'\w*\b',text,re.I))
                     for verb in ('fus','integrat','extract','transform','construct'))
        application=bool(re.search(r'用于|用来|\b(?:used?|appl\w*)\b',requirement,re.I))
        implementation=bool(re.search(r'implementation|procedure|pipeline',section,re.I))
        kind=int(method)+int(application and implementation)
    else:relation=0;kind=int(method)
    terms=set(re.findall(r'[a-z]{4,}',query.lower()))-{'arxiv','paper','method','methods','using'}
    overlap=sum(bool(re.search(r'\b'+re.escape(term)+r'\w*\b',text,re.I)) for term in terms)
    return (-int(background),kind*2+min(3,int(relation)),overlap)
