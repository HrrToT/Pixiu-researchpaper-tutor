"""Unverified writing division; never source permission or coverage approval."""
from copy import deepcopy
import json


def allocation(report, requirements, characters, protected_ids=()):
    if protected_ids:return None
    if not isinstance(requirements,(tuple,list)):return None
    valid={r.get('obligationId') for r in requirements if isinstance(r,dict) and isinstance(r.get('obligationId'),str)}
    if len(valid)!=len(requirements) or any(not oid for oid in valid):return None
    claims=report.get('claims',[]) if isinstance(report,dict) else None
    if not isinstance(claims,list):return None
    assignments={}
    for c in claims:
        if not isinstance(c,dict) or not isinstance(c.get('claimId'),str) or not c['claimId']:return None
        ids=c.get('obligationIds')
        if (not isinstance(ids,list) or not ids or any(not isinstance(v,str) or v not in valid for v in ids)
                or len(ids)!=len(set(ids)) or c.get('claimId') in assignments):return None
        assignments[c['claimId']]=list(ids)
    owners={}
    for oid in valid:
        candidates=[cid for cid,ids in assignments.items() if oid in ids]
        if candidates:
            size=min(len(assignments[cid]) for cid in candidates)
            narrow=[cid for cid in candidates if len(assignments[cid])==size]
            if len(narrow)==1:owners[oid]=narrow[0]
    primary={cid:[oid for oid in ids if owners.get(oid,cid)==cid] for cid,ids in assignments.items()}
    # Never erase a target or guess a distinct role for identical assignments.
    if not primary or any(not ids for ids in primary.values()):return None
    budgets={cid:None for cid in primary}
    if type(characters) is int and characters>=len(primary):
        total=sum(len(ids) for ids in primary.values())
        spare=characters-len(primary)
        budgets={cid:1+spare*len(ids)//total for cid,ids in primary.items()}
        for cid in list(primary)[:characters-sum(budgets.values())]:budgets[cid]+=1
    return {'version':1,'targets':[{'claimId':cid,'primaryObligationIds':ids,
        'detailElsewhere':[{'obligationId':oid,'claimId':owners[oid]} for oid in assignments[cid] if oid not in ids],
        'suggestedTextAndConditionsCharacters':budgets[cid]} for cid,ids in primary.items()]}


def prepare(request,report,requirements,characters,protected_ids=()):
    plan=allocation(report,requirements,characters,protected_ids)
    if plan is None:return request,{'version':1,'status':'not_applicable'}
    addition='\nWriting division (UNVERIFIED draft metadata, not coverage or evidence):\n'+json.dumps(plan,ensure_ascii=False,separators=(',',':'))+"""
Explain each target's primaryObligationIds in its own words. detailElsewhere delegates
only the detailed answer to the named sibling: do not repeat that entire explanation.
Keep every necessary condition on your own assertion. Keep all original IDs, kinds,
obligationIds and OWN evidence permissions; shared goals are not deleted or proved.
Identical/tied assignments may need complementary contributions; do not invent distinct
scientific roles or collapse claims. Suggested per-target budgets include conditions;
they share the SAME original total after layout reservation, never extra characters.
Do not turn optional equations into spoken arithmetic: that is still an equation, not
a plain explanation. Explain what changes and how its result is used next, from sources.
An unresolved sibling remains unresolved; never manufacture its answer in another target.
Whole-answer coverage and independent source/fact checks still follow.
"""
    from services.deep_research.audience_rewrite import MAX_INPUT_BYTES
    if len((request['prompt']+addition).encode('utf8'))>MAX_INPUT_BYTES:
        return request,{'version':1,'status':'input_capacity'}
    updated=deepcopy(request);updated['prompt']+=addition
    return updated,{'version':1,'status':'prepared','plan':plan}
