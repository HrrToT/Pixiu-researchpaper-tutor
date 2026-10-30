"""Frozen per-target answer ownership; never paper evidence or new permissions."""
from copy import deepcopy


GUIDANCE = '''Global question sets shared context/tone/length.
Each rejected target answers ONLY its bound frozen goals below, with needed premises.
No other-goal answers or absence claims. Shared goals allow complementary parts.
A missing citation proves no absence. Omit unsupported targets; keep IDs.
Bindings grant no factual support or source permission.
'''


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
