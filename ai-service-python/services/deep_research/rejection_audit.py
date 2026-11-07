"""Bind negative design feedback to exact supplied declarations, never approve it."""
from collections import Counter
from copy import deepcopy
import json

ROOTS = {
    'groups': {'factors'}, 'data': {'dataset','scenes','split','seeds','independentUnit','replication'},
    'controls': {'initialization','rendering','optimizer','otherInterventions'},
    'budget': {'baseline','recovery'}, 'analysis': {'effects','uncertainty','decision'},
    'hypothesis': {'statement','analysisClaimId','effectKeys','purpose'},
    'steps': {'refs','order','baselineMode','replicationMode','baselineInitialization',
        'componentInitializations','checkpointSelection','records'},
}


def roots_for_claim(claim):
    roots=ROOTS.get(claim.get('designRole'),set())
    if claim.get('designRole')=='steps' and type(claim.get('workflowContractVersion')) is int and claim['workflowContractVersion']==5:
        return roots | {'phases','frameIterations'}
    return roots

POLICY = '''Negative feedback must be auditable too. For status:failed add findings:1..6 items,
each exactly {kind:missing_field|incomplete|incompatible|unsupported,claimId:target or supplied
context ID,path:[keys/zero-based indices],reason:concise Chinese,value:EXACT supplied value}.
missing_field omits value and may name ONLY an absent text/executionSpec or absent top-level
executionSpec key from the supplied role grammar. Present null/empty/invalid values are NOT absent.
Other kinds bind an existing value under text, conditions or executionSpec. Read text AND conditions;
explain the actual defect of that value, not an absent duplicate. No invented metrics schema keys.
One finding states one precise defect. Point to the actual rejected dependency when necessary.
Passed rows use findings:[] and still need all independent positive audits. Exact bindings prove
neither that a rejection is scientifically correct nor that another target may pass.'''


def enabled(version):
    return type(version) is int and version in (5,6,7,8,9,10)


def _lookup(row,path):
    value=row
    for key in path:
        if isinstance(value,dict) and isinstance(key,str) and key in value:value=value[key]
        elif isinstance(value,list) and type(key) is int and 0<=key<len(value):value=value[key]
        else:return False,None
    return True,value


def validate(verdict,context):
    """Validate pointers and literal values, not the model's scientific judgement."""
    findings=verdict.get('findings')
    if verdict.get('status')=='passed':return [] if findings==[] else ['passed_with_missing_or_nonempty_findings']
    if not isinstance(findings,list) or not 1<=len(findings)<=6:return ['missing_findings']
    counts=Counter(c.get('claimId') for c in context if isinstance(c,dict) and isinstance(c.get('claimId'),str))
    rows={c['claimId']:c for c in context if isinstance(c,dict) and isinstance(c.get('claimId'),str)
        and counts[c['claimId']]==1 and c.get('kind') in ('proposal','suggestion','hypothesis')
        and type(c.get('designContractVersion')) is int and c['designContractVersion']==2}
    errors=[]
    for i,item in enumerate(findings):
        prefix='finding.'+str(i)
        if not isinstance(item,dict):errors.append(prefix+'.object');continue
        missing=item.get('kind')=='missing_field'
        expected={'kind','claimId','path','reason'}| (set() if missing else {'value'})
        if (set(item)!=expected or item.get('kind') not in ('missing_field','incomplete','incompatible','unsupported')
                or not isinstance(item.get('reason'),str) or not item['reason'].strip() or len(item['reason'])>600
                or not isinstance(item.get('claimId'),str) or item['claimId'] not in rows):
            errors.append(prefix+'.fields');continue
        row=rows[item['claimId']];path=item['path']
        if (not isinstance(path,list) or not 1<=len(path)<=12 or path[0] not in ('text','conditions','executionSpec')
                or any(not isinstance(k,str) and type(k) is not int for k in path)):
            errors.append(prefix+'.path');continue
        exists,value=_lookup(row,path)
        if missing:
            role=row.get('designRole')
            allowed=path==['text'] or (isinstance(role,str) and role in ROOTS and
                (path==['executionSpec'] or len(path)==2 and path[0]=='executionSpec'
                 and isinstance(path[1],str) and path[1] in roots_for_claim(row)))
            if exists or not allowed:errors.append(prefix+'.not_an_absent_schema_field')
        elif not exists:errors.append(prefix+'.missing_binding')
        else:
            try:exact=json.dumps(value,sort_keys=True,allow_nan=False)==json.dumps(item['value'],sort_keys=True,allow_nan=False)
            except (TypeError,ValueError,OverflowError):exact=False
            if not exact:errors.append(prefix+'.value_mismatch')
    return errors


def bind(verdict,context):
    result=deepcopy(verdict)
    # These annotations are server-owned, never a model's scheduling control.
    result.pop('rejectionAudit',None);result.pop('executionState',None)
    errors=validate(verdict,context)
    if errors:
        result.update(status='failed',executionState='received_invalid',
            reason='核验拒绝项没有绑定到实际输入，尚未形成可用判断；保留原始响应。')
        result['rejectionAudit']={'version':1,'bindingState':'invalid','errors':errors,
            'originalReason':verdict.get('reason'),'originalFindings':deepcopy(verdict.get('findings'))}
    elif verdict['status']=='failed':
        result['reason']='；'.join(item['reason'] for item in verdict['findings'])
        result['rejectionAudit']={'version':1,'bindingState':'verified',
            'findings':deepcopy(verdict['findings']),'scientificRejectionVerified':False}
    return result
