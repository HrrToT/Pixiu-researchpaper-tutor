"""Compile one authored content branch; never choose between conflicting drafts."""
from copy import deepcopy


def enabled(record,kind=None):
    from services.deep_research.factual_prompt import enabled as factual_enabled
    return (type(record.get('authoredBodyContractVersion')) is int and record['authoredBodyContractVersion'] in (1, 2)
        and record.get('scopeExpressionContractVersion')==5
        and factual_enabled(record,kind or record.get('state',{}).get('outputKind')))


GUIDANCE='''Use body with EXACTLY ONE key: {"prose":{"text":"actual wording","conditions":{}}}
OR {"boundary":{"observedSettings":[],"notEstablished":[{"type":"comparison_evidence","subjects":["A","B"],"quantity":"requested quantity"}]}}.
Use actual values, not the example labels. Boundary requires kind="inference". Never output text,conditions,scopeExpression at
claim top level, even empty/null. Other instructions about those canonical fields
refer to the compiled body: prose supplies text/conditions, boundary supplies the
scopeExpression and is rendered by the app. Compiled text still counts toward the
same length limit and receives all independent checks; the branch grants no support.'''


def reasoning_enabled(record, kind=None):
    return (enabled(record, kind) and record['authoredBodyContractVersion'] == 2
            and type(record.get('synthesisInputContractVersion')) is int
            and record['synthesisInputContractVersion'] == 1
            and type(record.get('factualPromptContractVersion')) is int
            and record['factualPromptContractVersion'] == 3
            and type(record.get('draftValidationContractVersion')) is int
            and record['draftValidationContractVersion'] == 1)


REASONING_GUIDANCE = '''body.reasoning is for a source-grounded LOCAL mechanism deduction, kind="inference".
Its premise and consequence are nonempty Chinese strings, joined with a newline;
the WHOLE text receives independent factual, numeric, scope and coverage checks.
Explain the actual operation and its logical consequence or limit, with necessary
conditions. A user prohibition is no source premise. Invent no comparator, setting
inventory or measurement to express this deduction. No author-wide absence follows.
Actual evidence-comparison/generalization bounds still require body.boundary and
its operator audits; never relabel them to evade checks. One body branch only.
'''


def guidance(record, kind=None):
    if not reasoning_enabled(record, kind):
        return GUIDANCE
    return GUIDANCE.replace('Use actual values, not the example labels.',
        'OR {"reasoning":{"premise":"source-grounded mechanism","consequence":"local deduction or limit"}}.\n'
        'Use actual values, not the example labels.', 1) + '\n' + REASONING_GUIDANCE


def fields(names):
    return ','.join([n for n in names.split(',') if n not in {'text','conditions','scopeExpression'}]+['body'])


def schema(value):
    return {**{k:deepcopy(v) for k,v in value.items() if k not in {'text','conditions','scopeExpression'}},
        'body':{'prose':{'text':'revised wording','conditions':{}}}}


def decode(claim, *, reasoning=False):
    if type(reasoning) is not bool:
        raise ValueError('Invalid authored reasoning policy')
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
    if reasoning and set(body)=={'reasoning'} and claim.get('kind')=='inference':
        value=body['reasoning']
        if (not isinstance(value,dict) or set(value)!={'premise','consequence'}
                or any(not isinstance(value[k],str) or not value[k].strip() for k in value)):
            raise ValueError('Explicit reasoning premise and consequence required')
        return {**result,'text':value['premise']+'\n'+value['consequence'],
                'conditions':{},'scopeExpression':None}
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
