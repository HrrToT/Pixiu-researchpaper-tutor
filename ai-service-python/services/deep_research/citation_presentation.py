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


def normalize(claim,aliases,quotes,*,version=1):
    """Only bracketed E labels that already occur in this claim's citations.

    Unknown/uncited labels, P/Q prose, equations/code and any E symbol present in
    own source quotes/context remain unchanged for the existing guard to assess.
    Version2 additionally accepts slash-separated markers and explicit source
    attribution; ambiguous arithmetic stays unchanged. It grants no references.
    The caller saves the original response and this separate presentation audit.
    """
    before=deepcopy(claim);result=deepcopy(claim)
    own={alias for alias,full in aliases.items() if full in claim.get('evidenceRefs',[]) and alias in quotes}
    protected_symbols={alias for alias in own if any(re.search(r'(?<![A-Za-z0-9_])'+re.escape(alias)+r'(?![A-Za-z0-9_])',
        quotes[key]) for key in own)}
    extended=type(version) is int and version==2
    removed=[]
    def text(value,path):
        protected=[(m.start(),m.end()) for m in _PROTECTED.finditer(value)]
        def remove(match):
            labels=set(re.findall(r'E[1-9]\d*',match.group()))
            if (not labels<=own or labels & protected_symbols
                    or any(start<=match.start()<end for start,end in protected)
                    or re.search(r'[=+*/^_-]\s*$',value[:match.start()])
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
                    or re.search(r'[=+*/^_-]\s*$',left) or re.match(r'\s*[=+*/^_-]',right)
                    or _MATH_AFTER.match(right)
                    or not (_BEFORE.search(left) or _AFTER.match(right))):
                return match.group()
            replacement='所引原文' if re.search(r'[\u4e00-\u9fff]',left[-12:]+right[:12]) else 'the cited passage'
            removed.append({'field':path,'marker':match.group(),'offset':match.start(),
                'kind':'source_attribution','replacement':replacement,
                'evidenceRefs':[aliases[label] for label in dict.fromkeys(re.findall(r'E[1-9]\d*',match.group()))]})
            return replacement
        return _ATTRIBUTION.sub(attribute,result)
    def values(value,path):
        if isinstance(value,str): return text(value,path)
        if isinstance(value,list): return [values(v,f'{path}[{i}]') for i,v in enumerate(value)]
        if isinstance(value,dict): return {k:values(v,f'{path}.{k}') for k,v in value.items()}
        return value
    if isinstance(result.get('text'),str): result['text']=text(result['text'],'text')
    if 'conditions' in result: result['conditions']=values(result['conditions'],'conditions')
    audit={'claimId':claim.get('claimId'),'originalText':before.get('text'),
           'originalConditions':before.get('conditions'),'normalizedText':result.get('text'),
           'normalizedConditions':result.get('conditions'),'removed':removed} if removed else None
    return result,audit
