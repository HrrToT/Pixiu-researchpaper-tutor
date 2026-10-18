"""Remove only unambiguous own citation markers, never substantive wording."""
from copy import deepcopy
import re

_IDS=r'E[1-9]\d*(?:\s*[,，、]\s*E[1-9]\d*)*'
_MARKER=re.compile(r'\(\s*'+_IDS+r'\s*\)|（\s*'+_IDS+r'\s*）|\[\s*'+_IDS+r'\s*\]')
_PROTECTED=re.compile(r'```[\s\S]*?```|`[^`\n]*`|\$\$[\s\S]*?\$\$|\$[^$\n]*\$')


def normalize(claim,aliases,quotes):
    """Only bracketed E labels that already occur in this claim's citations.

    Unknown/uncited labels, P/Q prose, equations/code and any E symbol present in
    own source quotes/context remain unchanged for the existing guard to assess.
    The caller saves the original response and this separate presentation audit.
    """
    before=deepcopy(claim);result=deepcopy(claim)
    own={alias for alias,full in aliases.items() if full in claim.get('evidenceRefs',[]) and alias in quotes}
    protected_symbols={alias for alias in own if any(re.search(r'(?<![A-Za-z0-9_])'+re.escape(alias)+r'(?![A-Za-z0-9_])',
        quotes[key]) for key in own)}
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
        return _MARKER.sub(remove,value)
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
