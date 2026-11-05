"""Bind actual operations for literal process requests, never scientific approval."""
import re
from itertools import product

_HOW = re.compile(r'(?:如何|怎样|怎么)[^。！？\n]{0,45}(?:用于|用来|使用|实现|生成|构建|提取|计算|训练|优化|更新|融合|工作|运作|运行|执行|处理|渲染|转换|估计|区分|检验)'
                  r'|\bhow\b[^.!?\n]{0,80}\b(?:use\w*|appl\w*|work\w*|operat\w*|comput\w*|train\w*|optimiz\w*|updat\w*|fus\w*|render\w*|extract\w*|convert\w*)\b'
                  r'|(?:具体|实际|操作|处理|训练|重建)(?:流程|步骤)',re.I)
_UNCERTAINTY = re.compile(r'^(?:是否|能否|有没有|有无|可否|能不能|\s*(?:whether|does|can|is)\b)',re.I)
_ACTION = re.compile(r'\b(?:comput\w*|render\w*|rasteriz\w*|fus\w*|integrat\w*|aggregat\w*|train\w*|optimiz\w*|penaliz\w*|align\w*|sampl\w*|construct\w*|updat\w*|transform\w*|minimiz\w*|distill\w*)\b'
                     r'|计算|渲染|光栅化|融合|聚合|累加|训练|优化|惩罚|约束|对齐|采样|构建|更新|变换|蒸馏|相乘|投影',re.I)
_SUMMARY = re.compile(r'用于|用来|用以|达到|提升|提高|改善|保持|优于|\b(?:used?\s+for|achiev\w*|improv\w*|maintain\w*|outperform\w*)\b',re.I)
_BARE = re.compile(r'^(?:使用|用于|采用|进行|用来|利用|通过|达到|提高|提升|保持|use|used|using|apply|applied|for|to|achieve|achieves|maintain|improve)$',re.I)

DRAFT_GUIDANCE='''For literal how/procedure requests, explain the actual operation connecting
the stated inputs to the intended artifact/state. Purpose, a method name or benchmark
benefits alone do not explain how. Use own sources; do not invent missing steps or
unrequested implementation parameters. Mark a precise gap if the operation is unavailable.'''

GUIDANCE='''For processRequired=true, covered/ready needs at least one processLinks row:
{"input":{"request":"exact request excerpt"},
 "operation":{"id":"own ID","field":"text or quote","excerpt":"exact actual operation"},
 "output":{"request":"exact request excerpt"}}.
Each role may instead bind {id,field,excerpt}. Operation MUST bind the supplied answer
or evidence, never the request. Input/output may use the literal requirement to avoid
repeating unambiguous context. Bind exact contiguous excerpts, not paraphrases.
Use text/conditions for answers; quote/sourceContext.before/sourceContext.after for
evidence. A bare 'used for', purpose, method name or achieved benchmark is not an
operation. Several own fields may jointly supply the relation; do not require one
source to state the entire workflow. Check actual semantic connection and EACH
requested part too: matching excerpts alone do not prove readiness or completeness.
No missing process may be invented from a title, abstract benefit or familiar method.
Partial/missing/not-ready may return processLinks=[]. Do not demand extra steps,
experimental results or parameters beyond the literal request.'''


def required(requirement):
    if isinstance(requirement,str) and re.search(r'(?:如何|怎样|怎么)(?:理解|看待|评价|解读|看懂|判断)|\bhow\s+(?:to\s+)?(?:understand|interpret|evaluate|judge)\b',requirement,re.I):return False
    return isinstance(requirement,str) and not _UNCERTAINTY.search(requirement.strip()) and bool(_HOW.search(requirement))


def fields(row, *, evidence=False):
    if not evidence:
        import json
        return {'text':row.get('text',''),'conditions':json.dumps(row.get('conditions',{}),ensure_ascii=False,sort_keys=True)}
    result={'quote':row.get('quote','')}
    context=row.get('sourceContext')
    if isinstance(context,dict):
        result.update({'sourceContext.'+key:value for key,value in context.items()
                       if key in ('before','after') and isinstance(value,str)})
    return result


def validate_links(links,entities,allowed,requirement):
    """Exact role bindings are necessary, never a semantic support verdict."""
    if not isinstance(links,list) or not 1<=len(links)<=4:return ['missing_process_links']
    errors=[]
    for link in links:
        if not isinstance(link,dict) or set(link)!={'input','operation','output'}:
            errors.append('invalid_process_link');continue
        resolved={};spans={}
        for role,binding in link.items():
            if not isinstance(binding,dict):errors.append('invalid_process_binding');continue
            if set(binding)=={'request'} and role!='operation':
                text=binding['request']
                if not isinstance(text,str) or not text.strip() or text not in requirement:
                    errors.append('unbound_process_request');continue
                resolved[role]=text;continue
            if set(binding)!={'id','field','excerpt'}:
                errors.append('invalid_process_binding');continue
            identity,field,text=binding['id'],binding['field'],binding['excerpt']
            if (not isinstance(identity,str) or identity not in allowed or not isinstance(field,str)
                    or not isinstance(text,str) or not text.strip()):
                errors.append('unbound_process_excerpt');continue
            full=entities.get(identity,{}).get(field)
            if not isinstance(full,str) or text not in full:
                errors.append('unbound_process_excerpt');continue
            positions=[m.start() for m in re.finditer('(?='+re.escape(text)+')',full)]
            if len(positions)>16:errors.append('ambiguous_process_excerpt');continue
            resolved[role]=text;spans[role]=[(identity,field,p,p+len(text)) for p in positions]
        if len(resolved)!=3:continue
        action=resolved['operation'].strip(' \t\r\n，。；,:;.')
        if (_BARE.fullmatch(action) or action in (resolved['input'],resolved['output'])
                or _SUMMARY.search(action) and not _ACTION.search(action)):
            errors.append('purpose_or_result_not_operation')
        if spans and not any(all(a[:2]!=b[:2] or a[3]<=b[2] or b[3]<=a[2]
                for i,a in enumerate(combo) for b in combo[i+1:]) for combo in product(*spans.values())):
            errors.append('overlapping_process_roles')
    return list(dict.fromkeys(errors))


def evidence_score(row):
    """Ranking hint only; no method names, paper identities or approval."""
    text=row.get('quote','')
    return min(12,len(_ACTION.findall(text))*2)+2*bool(re.search(r'\bthen\b|随后|然后|再',text,re.I))


def drafting_enabled(record):
    from services.deep_research.request_context import effective_question
    return (type(record.get('requestCoverageContractVersion')) is int
            and record['requestCoverageContractVersion']==4 and required(effective_question(record)))
