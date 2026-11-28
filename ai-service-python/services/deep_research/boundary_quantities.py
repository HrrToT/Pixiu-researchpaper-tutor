"""Reject invented numeric criteria in an epistemic boundary, never approve it."""
import re
from decimal import Decimal,InvalidOperation
from services.deep_research.selection import surrounding_context

# A comparator followed by a number is a criterion. Method names/version labels
# without a comparator are not measurements. Units remain literal (no conversion).
_UNIT=r'(?:%|dB(?:m|A)?|[kMGTmunµμ]?(?:B|b|m|s|Hz|W|J|V|A|g|K|Pa)|FPS|px|pixels?|frames?|samples?|steps?|iterations?|x|×)(?![A-Za-z])'
_THRESHOLD=re.compile(r'(?:小于|大于|不超过|不低于|不高于|至少|至多|差距[^，。；;\n]{0,12}?|容差[^，。；;\n]{0,8}?|[<>≤≥]=?|less than|greater than|at most|at least|within|below|above)\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*('+_UNIT+r')?',re.I)
_QUANTITY=re.compile(r'(?<![A-Za-z0-9_.])([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*('+_UNIT+r')?',re.I)


def _key(match):
    unit=match[2] or ''
    if unit.casefold() in {'db','fps'}:unit=unit.casefold()
    try:return Decimal(match[1]),unit
    except InvalidOperation:return None


def failures(claims,expressions,evidence,question):
    result=[]
    for claim in claims:
        expression=expressions.get(claim['claimId'])
        if not isinstance(expression,dict):continue
        refs=set(claim.get('evidenceRefs',[]))
        own=[e for e in evidence if e.get('evidenceId') in refs]
        texts=[str(question or '')]
        for item in own:
            texts.append(item.get('quote',''))
            context=surrounding_context(item)
            if isinstance(context,str):texts.append(context)
            elif isinstance(context,dict):texts.extend(context.get(k,'') for k in ('before','after'))
        texts=[t for t in texts if isinstance(t,str)]
        anchors={key for text in texts for m in _QUANTITY.finditer(text) if (key:=_key(m)) is not None}
        missing=[]
        for proposition in expression.get('notEstablished',[]):
            if not isinstance(proposition,str):continue
            for match in _THRESHOLD.finditer(proposition):
                if _key(match) not in anchors:
                    missing.append({'value':match[1],'unit':match[2] or ''})
        if missing:
            result.append({'claimId':claim['claimId'],'status':'failed',
                'reason':'unanchored_boundary_quantity',
                'unanchoredQuantities':missing})
    return result


GUIDANCE="""
A scope boundary must preserve the actual human proposition, not invent a numerical
meaning for words such as close/comparable. Include a numerical threshold only when
its quantity and unit are explicitly anchored in the human question or THIS point's
own original quotations/context. Do not turn an observed difference into a tolerance.
Do not share one metric's unit or tolerance across other metrics. If no criterion is
specified, keep the predicate qualitative and explain the actual bounded evidence.
The anchor check is only a prerequisite: correct metric association, units, relevance,
quantification and implication still need independent semantic review.
"""
