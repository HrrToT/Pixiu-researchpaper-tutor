"""Authored evidence sufficiency, not a paper-wide absence assertion or verdict."""

SCHEMA = {'type':'comparison_evidence', 'subjects':['actual paper/method A','actual paper/method B'],
          'quantity':'requested measurement or condition to compare'}

GUIDANCE = '''For authored evidence boundaries use kind="inference",text="",conditions={}, own evidenceRefs,
scopeExpression={"observedSettings":[{"subject":"method","attribute":"setting","value":"exact observed value"}],"notEstablished":[P]}.
Max4 settings/2 propositions; not both empty. Settings need own support.
P is either {"quantifier":"all|exists","domain":"explicit settings/datasets","subject":"method","comparator":"baseline","predicate":"positive result"}
or {"type":"comparison_evidence","subjects":["A","B"],"quantity":"requested measurement/condition"}.
all/exists is generalization. comparison_evidence means only THESE citations lack sufficient data/conditions
for that comparison. No invented
baseline none, author-wide omission, negative result or impossibility. Keep supported measurements;
limit an unresolved optional condition to that condition. Own sufficient data or a theorem establishing P makes the boundary fail.
The app renders settings and the unestablished P once; that text counts toward the limit and
receives independent factual/scope/coverage review.
Other points: scopeExpression=null, ordinary text. No approval is granted.
'''


def fields(value):
    if (not isinstance(value,dict) or set(value)!={'type','subjects','quantity'}
            or value['type']!='comparison_evidence'):
        raise ValueError('Explicit comparison evidence boundary required')
    subjects=value['subjects'];quantity=value['quantity']
    if (not isinstance(subjects,list) or not 2<=len(subjects)<=8
            or any(not isinstance(s,str) or not s.strip() for s in subjects)
            or len({s.strip() for s in subjects})!=len(subjects)
            or not isinstance(quantity,str) or not quantity.strip()):
        raise ValueError('Distinct comparison subjects and explicit quantity required')
    return '与'.join(subjects),quantity


def proposition(value):
    subjects,quantity=fields(value)
    return '当前所引证据提供了足以比较'+subjects+'的'+quantity+'的对应数据和必要条件'


def display(value):
    subjects,quantity=fields(value)
    return '当前引用不足以比较'+subjects+'的'+quantity+'。'
