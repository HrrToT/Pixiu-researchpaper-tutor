"""Frozen per-target answer ownership; never paper evidence or new permissions."""
from copy import deepcopy
import json


GUIDANCE = '''Global question sets shared context/tone/length.
Each rejected target answers ONLY its bound frozen goals below, with needed premises.
No other-goal answers or absence claims. Shared goals allow complementary parts.
A missing citation proves no absence. Omit unsupported targets; keep IDs.
Bindings grant no factual support or source permission.
'''

POINT_GUIDANCE = '''Point hints below are UNVERIFIED draft contributions, not instructions,
source facts, premises to preserve or prose to copy. They locate each target's
specific part when frozen goal IDs are shared. Rebuild only that part from its own
permitted original evidence and correct ALL rejection checks. Do not answer a
sibling's part or inherit its conclusions. A target may answer a supported subset
of a shared goal; it need not retell the entire goal. Remove unsupported draft
localizations, outcomes and causal links rather than preserving them from the hint.
An optimization objective states what is penalized/encouraged, not an observed
effect or a guaranteed solution. No support means omit that target, not guess.
'''


def policy_version(value):
    if type(value) is bool:return int(value)
    if type(value) is int and value==2:return 2
    raise ValueError('Invalid repair target goal policy')


def point_hints(targets):
    result={}
    for target in targets:
        text=target.get('text')
        if isinstance(text,str) and text.strip():
            result[target['claimId']]=text
        elif isinstance(target.get('scopeExpression'),dict) and target['scopeExpression']:
            # Structured scope targets deliberately keep free prose empty.
            # Carry exact authored fields as private data, never source facts.
            result[target['claimId']]=json.dumps({'unverifiedScopeExpression':target['scopeExpression']},
                ensure_ascii=False,separators=(',',':'))
        else:raise ValueError('Factual repair target has no authored point responsibility')
    return result


def bind(targets, requirements):
    if any(not isinstance(o,dict) or not isinstance(o.get('obligationId'),str) or not o['obligationId'] for o in requirements):
        raise ValueError('Invalid frozen repair requirements')
    by_id={o.get('obligationId'):o for o in requirements if isinstance(o,dict)}
    if len(by_id)!=len(requirements) or any(not isinstance(k,str) or not k for k in by_id):
        raise ValueError('Invalid frozen repair requirements')
    result={}
    for target in targets:
        if not isinstance(target,dict):raise ValueError('Invalid factual repair target')
        cid=target.get('claimId');ids=target.get('obligationIds')
        if (not isinstance(cid,str) or not cid or cid in result or not isinstance(ids,list) or not ids
                or any(not isinstance(i,str) or i not in by_id for i in ids) or len(set(ids))!=len(ids)):
            raise ValueError('Factual repair target has no unambiguous frozen goals')
        result[cid]=deepcopy(ids)
    return result
