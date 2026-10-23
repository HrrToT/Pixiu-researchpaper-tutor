"""Present unambiguous own citations without changing scientific assertions."""
from copy import deepcopy
import re

_IDS=r'E[1-9]\d*(?:\s*[,，、]\s*E[1-9]\d*)*'
_MARKER=re.compile(r'\(\s*'+_IDS+r'\s*\)|（\s*'+_IDS+r'\s*）|\[\s*'+_IDS+r'\s*\]')
_PROTECTED=re.compile(r'```[\s\S]*?```|`[^`\n]*`|\$\$[\s\S]*?\$\$|\$[^$\n]*\$')
_IDS2=r'E[1-9]\d*(?:\s*[,，、/]\s*E[1-9]\d*)*'
_MARKER2=re.compile(r'\(\s*'+_IDS2+r'\s*\)|（\s*'+_IDS2+r'\s*）|\[\s*'+_IDS2+r'\s*\]')
_ATTRIBUTION=re.compile(r'(?<![A-Za-z0-9_])'+_IDS2+r'(?![A-Za-z0-9_])')
_BEFORE=re.compile(r'(?:来自|依据|根据|参见|源于|证据|来源|引文)\s*$|\b(?:from|according to|see|evidence)\s*$',re.I)
_AFTER=re.compile(r'\s*(?:仅|只|还|明确|也)?(?:提及|说明|指出|报告|描述|表明|显示|给出|所述)|\s+(?:reports?|describes?|states?|shows?)\b',re.I)
_MATH_AFTER=re.compile(r'\s*(?:计算|求值|相除|相乘|比值|比率|比例|商|乘积|的(?:比值|比率|比例|商|乘积))|\s+(?:ratio|quotient|product|divided|multiplied)\b',re.I)
_REF_PART3=r'E[1-9]\d*(?:\s*[-–—]\s*E[1-9]\d*)?'
_REFERENCE3=re.compile(r'(?<![A-Za-z0-9_])(?P<prefix>(?:论文|原文|(?i:the paper|paper))\s*)?'
    r'(?P<marker>'+_REF_PART3+r'(?:\s*[,，、/]\s*'+_REF_PART3+r')*)(?![A-Za-z0-9_])')
_ACTION_BEFORE3=re.compile(r'按\s*$')
_ACTION_AFTER3=re.compile(r'\s*(?:执行|实施|进行|开展)')
_ACTION_AFTER4=re.compile(r'\s*(?:执行|实施|进行|开展|初始化|优化|训练|更新|构建|恢复)')
_PAREN_ACTION4=re.compile(r'[（(]\s*按\s*$')
_PAREN_END4=re.compile(r'\s*[）)]')
_AFTER3=re.compile(r'\s*(?:(?:仅|只|还|也)?(?:提供|明确)|'
    r'定义.{0,16}(?:操作|方法|步骤|机制)|为(?:论文|原文).{0,16}(?:操作|方法|步骤|机制)|用于(?:展示|说明|阐明))')
_SINGLE_AFTER3=re.compile(r'\s*为(?=[^，,；;。\n]{0,60}(?:场景|数据集|帧.{0,8}窗口|来源|片段))')
_MATH_AFTER3=re.compile(r'\s*(?:用于|用来)?(?:计算|求值|相除|相乘|相减|相加|减去|加上|比值|比率|差值|差异|商|乘积|'
    r'的(?:比值|比率|比例|差值|差异|差|商|乘积))|\s*(?:为|是|表示|作为)[^，,；;。\n]{0,25}(?:差值|差异|误差|比值|能量)|'
    r'\s+(?:ratio|quotient|product|difference|subtract\w*|divided|multiplied)\b',re.I)


def normalize(claim,aliases,quotes,*,version=1):
    """Only bracketed E labels that already occur in this claim's citations.

    Unknown/uncited labels, P/Q prose, equations/code and any E symbol present in
    own source quotes/context remain unchanged for the existing guard to assess.
    Version2 additionally accepts slash-separated markers and explicit source
    attribution. Version3 handles already-owned explicit paper/range references
    and the hypothesis's human-readable statement; other config is untouched.
    Version4 also recognizes explicit initialization/training attributions and
    parenthesized "(按E1-E3)" citations. Ambiguous arithmetic stays unchanged.
    This grants no references.
    The caller saves the original response and this separate presentation audit.
    """
    before=deepcopy(claim);result=deepcopy(claim)
    own={alias for alias,full in aliases.items() if full in claim.get('evidenceRefs',[]) and alias in quotes}
    protected_symbols={alias for alias in own if any(re.search(r'(?<![A-Za-z0-9_])'+re.escape(alias)+r'(?![A-Za-z0-9_])',
        quotes[key]) for key in own)}
    extended=type(version) is int and version in (2,3,4)
    modern=type(version) is int and version in (3,4)
    operational=type(version) is int and version==4
    removed=[]
    def text(value,path):
        protected=[(m.start(),m.end()) for m in _PROTECTED.finditer(value)]
        def remove(match):
            labels=set(re.findall(r'E[1-9]\d*',match.group()))
            if (not labels<=own or labels & protected_symbols
                    or any(start<=match.start()<end for start,end in protected)
                    or re.search(r'[=+*/^_-]\s*$',value[:match.start()])
                    or modern and _MATH_AFTER3.match(value[match.end():])
                    or match.group().startswith('(') and re.search(r'[A-Za-z0-9_]$',value[:match.start()])):
                return match.group()
            removed.append({'field':path,'marker':match.group(),'offset':match.start()})
            return ''
        result=(_MARKER2 if extended else _MARKER).sub(remove,value)
        if not extended:return result
        # Explicit source attribution only. Preserve every substantive word and
        # citation permission; do not erase arbitrary labels or paper symbols.
        protected=[(m.start(),m.end()) for m in _PROTECTED.finditer(result)]
        def attribute(match):
            labels=set(re.findall(r'E[1-9]\d*',match.group()))
            left,right=result[:match.start()],result[match.end():]
            if (not labels<=own or labels & protected_symbols
                    or any(start<=match.start()<end for start,end in protected)
                    or re.search(r'[=+*/^_–—-]\s*$' if modern else r'[=+*/^_-]\s*$',left)
                    or re.match(r'\s*[=+*/^_–—-]' if modern else r'\s*[=+*/^_-]',right)
                    or (_MATH_AFTER3 if modern else _MATH_AFTER).match(right)
                    or not (_BEFORE.search(left) or _AFTER.match(right))):
                return match.group()
            replacement='所引原文' if re.search(r'[\u4e00-\u9fff]',left[-12:]+right[:12]) else 'the cited passage'
            removed.append({'field':path,'marker':match.group(),'offset':match.start(),
                'kind':'source_attribution','replacement':replacement,
                'evidenceRefs':[aliases[label] for label in dict.fromkeys(re.findall(r'E[1-9]\d*',match.group()))]})
            return replacement
        result=_ATTRIBUTION.sub(attribute,result)
        if not modern:return result
        protected=[(m.start(),m.end()) for m in _PROTECTED.finditer(result)]
        def reference(match):
            labels=[];has_range=False
            for part in re.split(r'\s*[,，、/]\s*',match['marker']):
                endpoints=re.findall(r'E[1-9]\d*',part)
                if any(e not in own for e in endpoints):return match.group()
                if len(endpoints)==1:labels.extend(endpoints)
                else:
                    has_range=True;start,stop=(int(e[1:]) for e in endpoints)
                    if not 0<=stop-start<len(own):return match.group()
                    labels.extend(f'E{i}' for i in range(start,stop+1))
            labels=list(dict.fromkeys(labels))
            left,right=result[:match.start()],result[match.end():]
            if (not set(labels)<=own or set(labels)&protected_symbols
                    or any(a<=match.start()<b for a,b in protected)
                    or re.search(r'[=+*/^_–—-]\s*$',left) or re.match(r'\s*[=+*/^_–—-]',right)
                    or _MATH_AFTER3.match(right)
                    or not (match['prefix'] or _BEFORE.search(left) or _AFTER.match(right) or _AFTER3.match(right)
                        or len(labels)==1 and _SINGLE_AFTER3.match(right)
                        or _ACTION_BEFORE3.search(left) and (
                            (_ACTION_AFTER4 if operational else _ACTION_AFTER3).match(right)
                            or operational and _PAREN_ACTION4.search(left) and _PAREN_END4.match(right)))):
                return match.group()
            replacement='所引原文' if re.search(r'[\u4e00-\u9fff]',match.group()+left[-12:]+right[:12]) else 'the cited passage'
            removed.append({'field':path,'marker':match.group(),'offset':match.start(),
                'kind':'source_attribution_range' if has_range else 'source_attribution',
                'replacement':replacement,'evidenceRefs':[aliases[label] for label in labels]})
            return replacement
        return _REFERENCE3.sub(reference,result)
    def values(value,path):
        if isinstance(value,str): return text(value,path)
        if isinstance(value,list): return [values(v,f'{path}[{i}]') for i,v in enumerate(value)]
        if isinstance(value,dict): return {k:values(v,f'{path}.{k}') for k,v in value.items()}
        return value
    if isinstance(result.get('text'),str): result['text']=text(result['text'],'text')
    if 'conditions' in result: result['conditions']=values(result['conditions'],'conditions')
    original_statement=None
    if modern and result.get('designRole')=='hypothesis' and isinstance(result.get('executionSpec'),dict):
        statement=result['executionSpec'].get('statement')
        if isinstance(statement,str):
            normalized=text(statement,'executionSpec.statement')
            if normalized!=statement:
                original_statement=statement;result['executionSpec']['statement']=normalized
    audit={'claimId':claim.get('claimId'),'originalText':before.get('text'),
           'originalConditions':before.get('conditions'),'normalizedText':result.get('text'),
           'normalizedConditions':result.get('conditions'),'removed':removed} if removed else None
    if audit is not None and original_statement is not None:
        audit.update(originalStatement=original_statement,normalizedStatement=result['executionSpec']['statement'])
    return result,audit
