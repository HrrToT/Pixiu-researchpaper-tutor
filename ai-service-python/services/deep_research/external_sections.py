"""Literal PDF section boundaries for reading selection, never support verdicts."""
import re

_HEADING = re.compile(r'(?m)^[ \t]*(?P<number>\d{1,2}(?:\.\d{1,2}){0,4})[ \t]+(?P<title>[A-Za-z][^\n]{1,160})')
_DOTTED_HEADING = re.compile(r'(?m)^[ \t]*(?P<number>\d{1,2}(?:\.\d{1,2}){0,4})\.?[ \t]+(?P<title>[A-Za-z][^\n]{1,160})')
_REFERENCES = re.compile(r'(?m)^[ \t]*(?:REFERENCES|BIBLIOGRAPHY|参考文献)[ \t]*$')
_METHOD = re.compile(r'\b(?:method(?:s|ology)?|approach|algorithm|implementation|loss functions?|training procedure|optimization)\b',re.I)
_OTHER = re.compile(r'\b(?:introduction|related work|background|references|bibliography|conclusion|experiment|evaluation|results?|datasets?|baselines?|comparison|appendix)\b',re.I)
_NAV_METHOD=re.compile(r'\b(?:method(?:s|ology)?|approach|algorithm|implementation(?: details)?|loss functions?|training procedure|optimization|initialization|update rules?|derivation|formulation|estimation)\b',re.I)
_NAV_OTHER=re.compile(r'\b(?:introduction|related work|background|references|bibliography|conclusion|experiments?|evaluations?|results?|datasets?|baselines?|comparison|appendix|preliminar\w*|convergence|analysis|acknowledg\w*)\b',re.I)
_ASK = re.compile(r'解释|如何|怎样|怎么|为什么|机制|原理|流程|方法|\b(?:explain|how|why|mechanism|procedure)\b',re.I)
_BACKGROUND = re.compile(r'相关工作|背景方法|以往方法|传统方法|\b(?:related work|prior methods?|previous methods?|traditional methods?)\b',re.I)
_RESULTS = re.compile(r'报告.*结果|实验结果|评测结果|性能结果|性能比较|数据集表现|\b(?:benchmark|results? comparison|reported results?|evaluation results?)\b',re.I)
_MERGE_REFERENCE = re.compile(
    r'\b(?:combin\w*|merg\w*)[ \t\n]+(?:the[ \t\n]+)?(?:algorithm|procedure|steps|rule)\b'
    r'[^.!?;]{0,160}?(?:\bappendix\s+|§\s*)([A-Z](?:\.\d+){0,3})(?![A-Za-z0-9])',
    re.IGNORECASE,
)
_APPENDIX_HEADING = re.compile(
    r'^[ \t]*(?:Appendix[ \t]+)?([A-Z](?:\.\d+){0,3})[ \t]+'
    r'[^\n]{0,120}\b(?i:combin\w*|merg\w*)\b[^\n]{0,120}$',
    re.MULTILINE,
)


def method_requested(question, *, outline=False):
    return bool((_ASK.search(question) or outline and re.search(r'表示|表征|参数化|提取路径|重建路径|\b(?:representation|parameterization|mesh extraction)\b',question,re.I))
                and not _BACKGROUND.search(question) and not _RESULTS.search(question))


def enabled(record):
    return type(record.get('externalReadingContractVersion')) is int and record['externalReadingContractVersion'] in (1,2,3,4,5)


def spans(pages, *, outline=False,normalize_headings=False, terminal_number_period=False):
    """Keep page text/offsets; inherit numbered section paths across pages.

    This is conservative layout metadata. It neither attributes every sentence
    in a method section to its authors nor treats headings as scientific proof.
    """
    if type(outline) is not bool:raise ValueError("Invalid PDF outline policy")
    if type(normalize_headings) is not bool or normalize_headings and not outline:raise ValueError('Invalid normalized heading policy')
    if type(terminal_number_period) is not bool:
        raise ValueError('Invalid numbered heading policy')
    stack=[];result=[]
    headings = _DOTTED_HEADING if terminal_number_period else _HEADING
    for page in pages:
        text=page.get('text','');events=[]
        for m in headings.finditer(text):
            title=m['title'].split('. ',1)[0].strip()
            admission_title=title
            if normalize_headings:
                from services.deep_research.pdf_outline import normalized_title
                admission_title=normalized_title(title)
                inline_heading=('. ' in m['title'] and bool(_NAV_METHOD.fullmatch(admission_title) or _NAV_OTHER.fullmatch(admission_title)))
                if re.search(r'[=≤≥∑Σ]',title) or (re.search(r'[.!?](?:[ \t]|$)',m['title']) and not inline_heading):continue
            # Tables, numbered prose and mathematical rows must not become a
            # section merely because they start with a number.
            method_pattern,other_pattern=(_NAV_METHOD,_NAV_OTHER) if normalize_headings else (_METHOD,_OTHER)
            if not title or len(title.split())>15 or not ('.' in m['number'] or method_pattern.match(admission_title) or other_pattern.match(admission_title)):
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
                if normalize_headings:
                    bare=re.sub(r'^\S+\s+','',role_title)
                    role=('other' if _NAV_OTHER.match(bare) else 'method' if _NAV_METHOD.search(role_title)
                          else stack[-1][2] if stack else 'unknown')
                stack.append((number,title,role))
            start=offset
        if start<len(text):parts.append(_part(start,len(text),stack))
        result.append((page,parts))
    return result


def _part(start,end,stack):
    return {'start':start,'end':end,'section':' / '.join(entry[1] for entry in stack),
            'role':stack[-1][2] if stack else 'unknown'}


def select(pages,query,terms,*,seen=(),contract_version=1,follow_merge_reference=False):
    if type(contract_version) is not int or contract_version not in (1,2,3):raise ValueError("Invalid external reading policy")
    annotated=spans(pages,outline=contract_version in (2,3),**({'normalize_headings':True} if contract_version==3 else {}))
    method_request=method_requested(query,outline=contract_version in (2,3))
    if contract_version==3:
        from services.deep_research.method_navigation import requested
        method_request=requested(query)
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
    if follow_merge_reference:
        selected = _include_merge_procedure(annotated, selected)
    return selected


def _include_merge_procedure(annotated, selected):
    selected_numbers = {page['page'] for page, _ in selected}
    for anchor, _ in selected:
        for match in _MERGE_REFERENCE.finditer(anchor['text']):
            label = match.group(1).upper()
            candidates = []
            for pair in annotated:
                for heading in _APPENDIX_HEADING.finditer(pair[0]['text'][:6000]):
                    if heading.group(1) == label or heading.group(1).startswith(label + '.'):
                        candidates.append(pair)
                        break
            if len(candidates) != 1 or candidates[0][0]['page'] in selected_numbers:
                continue
            # Keep the page that established the pointer and stay within the
            # existing page cap. No links or requests are created by PDF text.
            replaced = next((pair for pair in reversed(selected) if pair[0] is not anchor), None)
            if replaced is not None:
                return [candidates[0] if pair is replaced else pair for pair in selected]
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
