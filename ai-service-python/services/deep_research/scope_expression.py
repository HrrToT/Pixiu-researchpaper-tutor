"""Render authored epistemic operators; never rewrite or approve a factual claim."""
from copy import deepcopy


def enabled(record):
    return (type(record.get('scopeExpressionContractVersion')) is int
            and record['scopeExpressionContractVersion'] in (1, 2, 3))


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


QUANTIFIED_GUIDANCE = GUIDANCE.replace(
    '"notEstablished":["positive stronger proposition not established by these quotations"]',
    '"notEstablished":[{"quantifier":"all or exists","domain":"explicit set of settings or datasets",'
    '"subject":"actual method","comparator":"actual comparison baseline",'
    '"predicate":"positive result, including metric and tolerance where applicable"}]') + '''
Every notEstablished item must be an object with exactly those five fields.
Choose all (every member) or exists (at least one member) explicitly; do not choose
a universal merely to make the boundary pass. State the actual comparison domain,
subject, comparator and positive predicate. Do not put negation or an assertion
that authors omitted experiments in these fields. A schema does not prove that
the domain or predicate is meaningful: the semantic reviewer still checks both.
'''


def guidance(version=1):
    if version==3:
        return QUANTIFIED_GUIDANCE+'''
The display uses 已报告设置 for observations, grouping identical subjects without
changing their attributes/values. Boundaries use 尚不能据此确认, with 普遍成立
for all and 存在…情形 for exists. These are evidence limits, not negative results.
The full rendered text still counts toward the human character limit.
'''
    return QUANTIFIED_GUIDANCE if version == 2 else GUIDANCE


def boundary_text(value):
    if not isinstance(value, dict) or set(value) != {'quantifier','domain','subject','comparator','predicate'}:
        raise ValueError('Explicit quantified boundary fields required')
    if value['quantifier'] not in ('all','exists'):
        raise ValueError('Explicit all or exists quantifier required')
    for name in ('domain','subject','comparator','predicate'):
        if not isinstance(value[name],str) or not value[name].strip():
            raise ValueError('Explicit domain, subject, comparator and predicate required')
    quantifier = '所有情形' if value['quantifier'] == 'all' else '至少一种情形'
    return ('在范围「'+value['domain']+'」内的'+quantifier+'中，'+value['subject']
            +'相对于'+value['comparator']+'，'+value['predicate'])


def review_expression(expression, version=1):
    result = deepcopy(expression)
    if version in (2,3):
        result['notEstablished'] = [boundary_text(p) for p in result['notEstablished']]
    return result


def materialize(claim, version=1):
    if type(version) is not int or version not in (1,2,3):
        raise ValueError('Unsupported scope expression version')
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
    if observations:
        if version==3:
            if all(s['subject']==settings[0]['subject'] for s in settings):
                body=settings[0]['subject']+'（'+'；'.join(s['attribute']+'：'+s['value'] for s in settings)+'）'
            else:body='；'.join(s['subject']+'（'+s['attribute']+'：'+s['value']+'）' for s in settings)
            statements.append('已报告设置：'+body+'。')
        else:statements.append('所引来源报告的评估设置包括：'+'；'.join(observations)+'。')
    if boundaries:
        rendered = [boundary_text(p) if version in (2,3) else text(p) for p in boundaries]
        if version==3:
            for p in boundaries:
                if p['quantifier']=='all':
                    statements.append('尚不能据此确认'+p['subject']+'相对'+p['comparator']+'的“'+p['predicate']
                        +'”在'+p['domain']+'中普遍成立。')
                else:
                    statements.append('尚不能据此确认在'+p['domain']+'中存在'+p['subject']+'相对'+p['comparator']
                        +'“'+p['predicate']+'”的情形。')
        else:statements.append('这些引用不足以证明：'+'；'.join(rendered)+'。')
    result['text'] = ''.join(statements)
    return result, {'claimId':result.get('claimId'),'expression':deepcopy(expression),
                    'renderedText':result['text'],'verification':'unchecked'}
