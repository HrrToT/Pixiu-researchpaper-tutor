"""Generic criterion navigation over owned literal passages; never approval."""
import re
import unicodedata

_CONCEPT=re.compile(r'是什么|什么是|定义|含义|记录什么|表示什么|代表什么|估计什么|'
    r'解释|讲解|如何|怎样|怎么|为什么|原理|机制|流程|适用|边界|局限|'
    r'\b(?:what .{0,35}(?:mean|record|represent|estimate|store)|defin\w*|meaning|explain|how|why|mechanism|limitations?|scope)\b',re.I)
_EXCLUDE=re.compile(r'参考文献|相关工作|报告.*结果|主要结果|定量结果|实验结果|评测结果|性能比较|'
    r'\b(?:bibliograph\w*|related work|reported results?|main results?|quantitative results?|benchmark comparison|evaluation results?)\b',re.I)
_WHY=re.compile(r'为什么|为何|\bwhy\b',re.I)
_HOW=re.compile(r'如何|怎样|怎么|流程|步骤|\b(?:how|procedure)\b',re.I)
_LIMIT=re.compile(r'边界|局限|适用|\b(?:limitations?|scope|applicability)\b',re.I)
_DEFINE=re.compile(r'\b(?:defin\w*|refer\w* to|estimates? of|moving averages?|represents?|records?|stores?)\b|定义|表示为|记录',re.I)
_CAUSE=re.compile(r'\b(?:because|due to|caus\w*|leading to|leads? to|results? in|counteract\w*)\b|因为|导致|由于',re.I)
_ACTION=re.compile(r'\b(?:comput\w*|divid\w*|updat\w*|subtract\w*|normaliz\w*|fus\w*|extract\w*|transform\w*|construct\w*|convert\w*)\b|计算|相除|除以|更新|归一化|融合|提取',re.I)
_BOUND=re.compile(r'\b(?:if|under|assum\w*|provided|bounded|conditions?)\b|如果|假设|条件|前提',re.I)
_STOP={'arxiv','paper','method','methods','algorithm','definition','definitions','explain','what','which','where',
       'does','with','from','that','this','their','according','source','original'}


def enabled(record):
    return type(record.get('externalReadingContractVersion')) is int and record['externalReadingContractVersion']==3


def requested(question):
    from services.deep_research.external_sections import method_requested,_BACKGROUND,_RESULTS
    return (isinstance(question,str) and not (_EXCLUDE.search(question) or _BACKGROUND.search(question) or _RESULTS.search(question))
        and bool(_CONCEPT.search(question) or method_requested(question,outline=True)))


def priority(row,requirement,query='',response_type=''):
    from services.deep_research.reading_roles import quality
    if not requested(requirement):return (0,0,0,0,0)
    text=unicodedata.normalize('NFKC',row.get('quote',''))
    from services.deep_research.pdf_outline import normalized_title
    section=normalized_title(str((row.get('location') or {}).get('section','')))
    background=bool(re.search(r'related work|background|references|bibliograph',section,re.I))
    q=quality({'text':text,'location':row.get('location',{})},requirement)
    if background or q!=(True,True):return (-1,0,0,0,0)
    method=(row.get('location') or {}).get('sectionRole')=='method'
    if _WHY.search(requirement):relation=3*bool(_CAUSE.search(text))+bool(_DEFINE.search(text))
    elif _HOW.search(requirement) or response_type=='procedure':relation=min(3,len(_ACTION.findall(text)))
    elif _LIMIT.search(requirement) or response_type=='limitation':relation=3*bool(_BOUND.search(text))
    else:relation=3*bool(_DEFINE.search(text))
    # Use the original translated search terms, not invented answer tokens.
    terms=set(re.findall(r'[a-z]{3,}',str(query).casefold()))-_STOP
    title_terms=set(re.findall(r'[a-z]{3,}',str(row.get('sourceTitle','')).casefold()))
    terms-=title_terms
    words=re.findall(r'[a-z]+',text.casefold())
    hits=sum(any(w.startswith(t[:5] if len(t)>5 else t) for w in words) for t in terms)
    return (int(relation>0),relation,int(method),hits,-len(text))


def bundle(rows,requirement,query='',response_type=''):
    """At most three exact existing passages for complementary operations/context."""
    ranked=sorted(rows,key=lambda e:priority(e,requirement,query,response_type),reverse=True)
    if not ranked or priority(ranked[0],requirement,query,response_type)[0]<=0:return []
    lead=ranked[0];leads=[lead]
    if _HOW.search(requirement) or response_type=='procedure':
        def actions(row):return {m.group().casefold()[:5] for m in _ACTION.finditer(row.get('quote',''))}
        secondary=next((e for e in ranked[1:] if priority(e,requirement,query,response_type)[0]>0
            and priority(e,requirement,query,response_type)[3]>0 and actions(e)-actions(lead)),None)
        if secondary is not None:leads.append(secondary)
    result=[]
    # Anaphoric operations/causes need their actual immediately preceding
    # context, not an invented definition of "this term" or "these estimates".
    for lead in leads:
        loc=lead.get('location') or {}
        if re.search(r'\b(?:this|these|therefore|thus|above|previous)\b|这些|该项|因此',lead.get('quote','')[:170],re.I):
            start=loc.get('sourcePassageStart')
            previous=[e for e in rows if e is not lead
                and all(isinstance(lead.get(k),str) and lead[k] for k in ('sourceId','sourceWorkId','sourceVersionId','contentHash'))
                and all(e.get(k)==lead.get(k) for k in ('sourceId','sourceWorkId','sourceVersionId','contentHash'))
                and all((e.get('location') or {}).get(k)==loc.get(k) for k in ('page','offset'))
                and type(start) is int and start>0 and (e.get('location') or {}).get('sourcePassageEnd')==start]
            group=[previous[0],lead] if len(previous)==1 else [lead]
        else:group=[lead]
        additions=[e for e in group if e not in result]
        if len(result)+len(additions)<=3:result.extend(additions)
    return result
