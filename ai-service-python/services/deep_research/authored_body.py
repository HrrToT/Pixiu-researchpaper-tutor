"""Compile one authored content branch; never choose between conflicting drafts."""
from copy import deepcopy


def enabled(record,kind=None):
    from services.deep_research.factual_prompt import enabled as factual_enabled
    return (type(record.get('authoredBodyContractVersion')) is int and record['authoredBodyContractVersion']==1
        and record.get('scopeExpressionContractVersion')==5
        and factual_enabled(record,kind or record.get('state',{}).get('outputKind')))


GUIDANCE='''Use body with EXACTLY ONE key: {"prose":{"text":"actual wording","conditions":{}}}
OR {"boundary":{"observedSettings":[],"notEstablished":[{"type":"comparison_evidence","subjects":["A","B"],"quantity":"requested quantity"}]}}.
Use actual values, not the example labels. Boundary requires kind="inference". Never output text,conditions,scopeExpression at
claim top level, even empty/null. Other instructions about those canonical fields
refer to the compiled body: prose supplies text/conditions, boundary supplies the
scopeExpression and is rendered by the app. Compiled text still counts toward the
same length limit and receives all independent checks; the branch grants no support.'''


def fields(names):
    return ','.join([n for n in names.split(',') if n not in {'text','conditions','scopeExpression'}]+['body'])


def schema(value):
    return {**{k:deepcopy(v) for k,v in value.items() if k not in {'text','conditions','scopeExpression'}},
        'body':{'prose':{'text':'revised wording','conditions':{}}}}


def decode(claim):
    if not isinstance(claim,dict) or {'text','conditions','scopeExpression'}&set(claim):
        raise ValueError('Authored body cannot coexist with canonical prose or scope fields')
    body=claim.get('body')
    if not isinstance(body,dict) or len(body)!=1:raise ValueError('Exactly one authored body branch required')
    result=deepcopy(claim);result.pop('body')
    if set(body)=={'prose'}:
        prose=body['prose']
        if (not isinstance(prose,dict) or set(prose)!={'text','conditions'}
                or not isinstance(prose['text'],str) or not prose['text'].strip()
                or not isinstance(prose['conditions'],dict)):
            raise ValueError('Explicit prose text and conditions required')
        return {**result,**deepcopy(prose),'scopeExpression':None}
    if set(body)=={'boundary'} and claim.get('kind')=='inference' and isinstance(body['boundary'],dict):
        return {**result,'text':'','conditions':{},'scopeExpression':deepcopy(body['boundary'])}
    raise ValueError('Invalid authored boundary branch')


def scope_guidance(version):
    from services.deep_research.factual_prompt import scope_guidance as canonical
    return canonical(version).replace(
        'kind="inference",text="",conditions={}, own evidenceRefs,\nscopeExpression=',
        'kind="inference", own evidenceRefs, body.boundary=').replace(
        'Other points: scopeExpression=null, ordinary text.',
        'Other points use body.prose with text/conditions.')


def required_scope_ids(state,report):
    ids={c.get('claimId') for c in report.get('claims',[]) if isinstance(c,dict)}
    required=[a['claimId'] for a in state.get('synthesisScopeExpressionAudit',[])
        if isinstance(a,dict) and a.get('claimId') in ids and isinstance(a.get('expression'),dict)]
    for item in (state.get('draftValidationAudit') or {}).get('rejected',[]):
        claim=item.get('originalClaim',{});body=claim.get('body') or {}
        if (item.get('claimId') in ids and (isinstance(claim.get('scopeExpression'),dict)
                or isinstance(body,dict) and 'boundary' in body)):
            required.append(item['claimId'])
    return list(dict.fromkeys(required))


def edit_anchor(claim):
    """Exact draft deletion provenance only, never a chosen public content branch."""
    if isinstance(claim.get('text'),str):return claim,['text']
    body=claim.get('body');prose=body.get('prose') if isinstance(body,dict) else None
    if isinstance(prose,dict) and isinstance(prose.get('text'),str):
        return {**claim,'text':prose['text']},['body','prose','text']
    return claim,None
