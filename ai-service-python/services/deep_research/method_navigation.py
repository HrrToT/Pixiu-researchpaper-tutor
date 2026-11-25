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
_ROLE_QUERY = re.compile(r'起什么作用|有什么作用|作用是什么|做了什么|用来做什么|'
                         r'\b(?:what (?:role|purpose)|what (?:does|did) [^?.!\n]{1,45} do)\b', re.I)
_CONTENT_QUERY = re.compile(r'(?:保留|存储|包含|保存)(?:了)?(?:什么|哪些)|'
                            r'\bwhat\b[^?.!\n]{0,40}\b(?:retain\w*|stor\w*|keep\w*|contain\w*)\b', re.I)
_ROLE_ACTION = re.compile(r'\b(?:apply|applie[sd]|operat\w+|comput\w+|aggregat\w+|cluster\w+|enabl\w+|used to)\b'
                          r'|计算|汇总|用于|合并', re.I)
_CONTENT_ACTION = re.compile(r'\b(?:concatenat\w+|append\w*|retain\w*|stor\w+|sav\w+|contain\w*|keeps?)\b'
                             r'|拼接|保留|存储|包含', re.I)
_DEFINE=re.compile(r'\b(?:defin\w*|refer\w* to|estimates? of|moving averages?|represents?|records?|stores?)\b|定义|表示为|记录',re.I)
_CAUSE=re.compile(r'\b(?:because|due to|caus\w*|leading to|leads? to|results? in|counteract\w*)\b|因为|导致|由于',re.I)
_ACTION=re.compile(r'\b(?:comput\w*|divid\w*|updat\w*|subtract\w*|normaliz\w*|fus\w*|extract\w*|transform\w*|construct\w*|convert\w*)\b|计算|相除|除以|更新|归一化|融合|提取',re.I)
_DETAIL_ACTION=re.compile(r'\b(?:prun\w*|recover\w*|distill\w*|quantiz\w*|encod\w*|decod\w*|optim\w*|fine.tun\w*|densif\w*|project\w*|filter\w*|creat\w*|adapt\w*|rasteriz\w*|render\w*|split\w*|clon\w*)\b|剪枝|恢复|蒸馏|量化|编码|解码|优化|微调|投影|筛选|创建|自适应|渲染|分裂|克隆',re.I)
_OPERATIVE_REQUEST=re.compile(r'机制|原理|流程|管线|步骤|阶段|场景表示|表示要素|存储形式|额外处理|开销|成本|代价|\b(?:mechanism|pipeline|procedur\w*|steps?|stages?|overhead|cost)\b',re.I)
_BOUND=re.compile(r'\b(?:if|under|assum\w*|provided|bounded|conditions?)\b|如果|假设|条件|前提',re.I)
_STOP={'arxiv','paper','method','methods','algorithm','definition','definitions','explain','what','which','where',
       'does','with','from','that','this','their','according','source','original'}


def enabled(record):
    return type(record.get('externalReadingContractVersion')) is int and record['externalReadingContractVersion']==3


def requested(question):
    from services.deep_research.external_sections import method_requested,_BACKGROUND,_RESULTS
    return (isinstance(question,str) and not (_EXCLUDE.search(question) or _BACKGROUND.search(question) or _RESULTS.search(question))
        and bool(_CONCEPT.search(question) or _ROLE_QUERY.search(question) or _CONTENT_QUERY.search(question)
                 or method_requested(question,outline=True)))


def priority(row,requirement,query='',response_type='',*,operations=False):
    if type(operations) is not bool:raise ValueError('Invalid operation navigation policy')
    from services.deep_research.reading_roles import quality
    operation_request=(operations and response_type in {'identification','explanation','procedure'}
                       and not _EXCLUDE.search(requirement)
                       and bool(_OPERATIVE_REQUEST.search(requirement)))
    if not requested(requirement) and not operation_request:return (0,0,0,0,0)
    text=unicodedata.normalize('NFKC',row.get('quote',''))
    from services.deep_research.pdf_outline import normalized_title
    section=normalized_title(str((row.get('location') or {}).get('section','')))
    background=bool(re.search(r'related work|background|references|bibliograph',section,re.I))
    q=quality({'text':text,'location':row.get('location',{})},requirement)
    if background or q!=(True,True):return (-1,0,0,0,0)
    method=(row.get('location') or {}).get('sectionRole')=='method'
    if operation_request:
        # A measurement packet or benchmark retraining note is not a method
        # operation merely because it repeats the method name or a cost word.
        relation=0 if row.get('tableData') or text.lstrip().startswith('Table caption:') else min(3,
            len({m.group().casefold()[:5] for p in (_ACTION,_DETAIL_ACTION) for m in p.finditer(text)}))
    elif _CONTENT_QUERY.search(requirement):
        relation = min(3, len(_CONTENT_ACTION.findall(text)))
    elif _ROLE_QUERY.search(requirement):
        relation = min(3, len(_ROLE_ACTION.findall(text)))
    elif _WHY.search(requirement):relation=3*bool(_CAUSE.search(text))+bool(_DEFINE.search(text))
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


def bundle(rows,requirement,query='',response_type='',*,operations=False):
    """At most three exact existing passages for complementary operations/context."""
    rank=lambda row:priority(row,requirement,query,response_type,**({'operations':True} if operations else {}))
    if type(operations) is not bool:raise ValueError('Invalid operation navigation policy')
    ranked=sorted(rows,key=rank,reverse=True)
    if not ranked or rank(ranked[0])[0]<=0:return []
    lead=ranked[0];leads=[lead]
    if _HOW.search(requirement) or response_type=='procedure' or operations:
        def actions(row):
            text=row.get('quote','')
            return {m.group().casefold()[:5] for p in ((_ACTION,_DETAIL_ACTION) if operations else (_ACTION,)) for m in p.finditer(text)}
        secondary=next((e for e in ranked[1:] if rank(e)[0]>0
            and (operations or rank(e)[3]>0) and actions(e)-actions(lead)),None)
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
