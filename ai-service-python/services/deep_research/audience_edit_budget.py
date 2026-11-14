"""Server-owned fixed points and the remaining reader-edit character budget."""
from copy import deepcopy
import json


def enabled(record):
    from services.deep_research.answer_constraints import requested_character_limit
    from services.deep_research.request_context import effective_question
    limit=requested_character_limit(effective_question(record))
    return (type(record.get('audienceBudgetContractVersion')) is int
            and record['audienceBudgetContractVersion']==1
            and type(record.get('audienceRewriteContractVersion')) is int
            and record['audienceRewriteContractVersion']==9
            and type(limit) is int and 0<limit<=700)


def allocation(report,question,protected_ids):
    from services.deep_research.answer_constraints import answer_character_count,requested_character_limit
    claims=report.get('claims') if isinstance(report,dict) else None
    if (not isinstance(claims,list) or not claims
        or any(not isinstance(c,dict) or not isinstance(c.get('claimId'),str)
               or not c['claimId'] or not isinstance(c.get('text'),str)
               or not isinstance(c.get('conditions',{}),dict) for c in claims)):
        raise ValueError('Invalid reader budget draft')
    ids=[c['claimId'] for c in claims]
    if len(set(ids))!=len(ids):raise ValueError('Ambiguous reader budget target')
    if (not isinstance(protected_ids,(list,tuple)) or not protected_ids
        or any(not isinstance(k,str) for k in protected_ids)
        or len(set(protected_ids))!=len(protected_ids) or not set(protected_ids)<=set(ids)):
        raise ValueError('Invalid fixed reader targets')
    limit=requested_character_limit(question)
    if type(limit) is not int or limit<=0:raise ValueError('Fixed reader edit needs an explicit length limit')
    fixed=[c for c in claims if c['claimId'] in protected_ids]
    editable=[c for c in claims if c['claimId'] not in protected_ids]
    used=answer_character_count({'claims':fixed})
    return {'totalCharacters':limit,'fixedCharacters':used,'editableCharacters':max(0,limit-used),
            'protectedClaimIds':[c['claimId'] for c in fixed],'editableClaimIds':[c['claimId'] for c in editable]}


def prepare(report,evidence,question,protected_ids,base_prepare,options, *, responsibilities=False):
    if type(responsibilities) is not bool:raise ValueError('Invalid reader responsibility policy')
    budget=allocation(report,question,protected_ids)
    if not budget['editableClaimIds']:return None,'no_editable_targets'
    if not budget['editableCharacters']:return None,'fixed_points_exhaust_limit'
    subset={**deepcopy(report),'claims':[deepcopy(c) for c in report['claims'] if c['claimId'] in budget['editableClaimIds']]}
    request,reason=base_prepare(subset,evidence,question,**options)
    if reason:return request,reason
    request=deepcopy(request)
    prompt=request['prompt'].replace(f"Total ALL text+conditions character limit: {budget['totalCharacters']}.",
        f"Total text+conditions of ONLY editable targets must fit {budget['editableCharacters']} characters.",1)
    context=[{k:c[k] for k in ('claimId','text','conditions') if k in c} for c in report['claims'] if c['claimId'] in protected_ids]
    prompt+='\nServer-owned reader edit budget: '+json.dumps(budget,ensure_ascii=False,separators=(',',':'))+'''
The original question's total limit includes the fixed points below. Return ONLY
editableClaimIds; do not return, copy or alter any protectedClaimIds. The server
retains those complete original objects. Fit ALL editable text+conditions together
in editableCharacters. Spend words on requested actions and explanations, not optional
formulas or examples. Do not claim a missing answer part is covered. Fixed context
is UNVERIFIED draft context, not paper evidence or permission to borrow citations;
each editable target still needs its own original supplied quotations. Independent
source/factual/scope/coverage checks still follow; this edit grants no approval.
Fixed answer context (server merges it, never output it):
'''+json.dumps(context,ensure_ascii=False,separators=(',',':'))
    if responsibilities:
        from services.deep_research.audience_responsibilities import append
        try:
            prompt=append(prompt,report,options.get('requirement_context',()),protected_ids)
        except ValueError:
            return None,'invalid_point_responsibilities'
    from services.deep_research.audience_rewrite import MAX_INPUT_BYTES
    if len(prompt.encode('utf8'))>MAX_INPUT_BYTES:return None,'input_capacity'
    return {**request,'prompt':prompt},None


def merge(report,content,parse,question,protected_ids,base_merge,options,rejection):
    def reject(reason):
        if rejection:rejection(reason)
        return None
    budget=allocation(report,question,protected_ids)
    try:raw=parse(content)
    except (ValueError,TypeError):return reject('invalid_json')
    if not isinstance(raw,dict) or set(raw)!={'claims'} or not isinstance(raw['claims'],list):return reject('invalid_schema')
    if any(isinstance(c,dict) and c.get('claimId') in protected_ids for c in raw['claims']):return reject('protected_target_in_response')
    subset={**deepcopy(report),'claims':[deepcopy(c) for c in report['claims'] if c['claimId'] in budget['editableClaimIds']]}
    edited=base_merge(subset,content,lambda _:raw,question,rejection=rejection,**options)
    if edited is None:return None
    patches={c['claimId']:c for c in edited['claims']}
    combined=deepcopy(report)
    combined['claims']=[deepcopy(patches.get(c['claimId'],c)) for c in report['claims']]
    from services.deep_research.audience_point_scope import collapsed_distinct_points
    if collapsed_distinct_points({c['claimId']:c for c in report['claims']},{c['claimId']:c for c in combined['claims']}):
        return reject('collapsed_distinct_points')
    from services.deep_research.answer_constraints import answer_character_count
    if answer_character_count(combined)>budget['totalCharacters']:return reject('character_limit')
    return combined
