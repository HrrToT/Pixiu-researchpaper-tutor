"""Render authored epistemic operators; never rewrite or approve a factual claim."""
from copy import deepcopy


def enabled(record):
    return (type(record.get('scopeExpressionContractVersion')) is int
            and record['scopeExpressionContractVersion'] == 1)


SCHEMA = {'observedSettings':[{'subject':'actual method/experiment',
    'attribute':'actual evaluated setting name','value':'exact observed setting'}],
    'notEstablished':['positive stronger proposition NOT established by the own supplied evidence']}

GUIDANCE = '''For a factual answer point explaining observed settings or an evidence boundary,
use scopeExpression instead of freely writing an exclusive condition. The claim must
have kind="inference", text="", conditions={}, and its own evidenceRefs. Add:
scopeExpression={"observedSettings":[{"subject":"actual method/experiment",
"attribute":"evaluated setting name","value":"exact setting"}],
"notEstablished":["positive stronger proposition not established by these quotations"]}.
Each array may be empty, but at least one must be nonempty; at most 4 settings and 2
stronger propositions. The app renders observations as reported settings, and the
stronger propositions under 'these citations do not establish'. Do not write 'only
works', necessary conditions, missing experiments, or conclusions in setting values.
These operators do not grant factual support: settings need own original quotations,
and the stronger inference must actually remain unestablished. A universal theorem
cannot be described as a mere finite observation to manufacture uncertainty.
Other points use scopeExpression=null and ordinary text. Do not add a second text
version for a scope expression; conflicting text is rejected, not silently removed.
The compiled text still receives ordinary factual, scope and whole-answer review.
'''


def materialize(claim):
    result = deepcopy(claim)
    expression = result.pop('scopeExpression', None)
    if expression is None: return result, None
    if (result.get('kind') != 'inference' or result.get('text') != ''
            or result.get('conditions') != {} or not isinstance(expression, dict)
            or set(expression) != {'observedSettings','notEstablished'}):
        raise ValueError('Scope expression cannot overwrite authored factual prose')
    settings = expression['observedSettings']; boundaries = expression['notEstablished']
    if (not isinstance(settings,list) or len(settings)>4 or not isinstance(boundaries,list)
            or len(boundaries)>2 or not (settings or boundaries)):
        raise ValueError('Invalid scope expression cardinality')
    def text(value):
        if not isinstance(value,str) or not value.strip():
            raise ValueError('Scope fields must be explicit nonempty strings')
        return value  # Preserve the complete authored value; no repair/truncation.
    observations = []
    for setting in settings:
        if not isinstance(setting,dict) or set(setting) != {'subject','attribute','value'}:
            raise ValueError('Invalid observed setting fields')
        observations.append(text(setting['subject'])+'，'+text(setting['attribute'])+'='+text(setting['value']))
    statements = []
    if observations: statements.append('所引来源报告的评估设置包括：'+'；'.join(observations)+'。')
    if boundaries: statements.append('这些引用不足以证明：'+'；'.join(text(p) for p in boundaries)+'。')
    result['text'] = ''.join(statements)
    return result, {'claimId':result.get('claimId'),'expression':deepcopy(expression),
                    'renderedText':result['text'],'verification':'unchecked'}
