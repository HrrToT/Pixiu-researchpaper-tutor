"""Frozen per-target answer ownership; never paper evidence or new permissions."""
from copy import deepcopy


GUIDANCE = '''The global human question supplies shared context, tone and length limits.
Each rejected target answers ONLY its bound frozen goals below, not the whole
question. Repair supporting premises needed for those goals; do not append answers
or evidence-availability statements about another target's goals. Several targets
may share a goal and contribute different supported parts; no target must retell
all other parts. A missing citation is not a request to add an absence assertion.
If its own goal cannot be answered with permitted evidence, omit that target and
leave a gap rather than answering other goals. Do not relabel IDs to expand scope.
These goal bindings constrain the task, not factual support or source permissions.
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
