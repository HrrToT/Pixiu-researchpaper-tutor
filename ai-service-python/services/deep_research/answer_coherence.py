"""Bound a joint-answer consistency decision to exact accepted answer fields."""
from copy import deepcopy
from services.deep_research.contracts import digest


GUIDANCE='''
Also append EXACTLY ONE additional array row:
{"auditType":"answer_coherence","coherent":true,"issues":[]}.
Judge the COMPLETE accepted answer jointly, including conditions/executionSpec.
Use coherent=false only for an actual contradiction or unresolved scope ambiguity
that makes the combined answer misleading. An unqualified claim that the provided
evidence does not explain X conflicts with a subsequent explanation of X unless
the answer clearly distinguishes which sources, conditions or scopes it means.
Different datasets, versions, proposed versus measured choices, or explicitly
qualified source-specific limits are NOT contradictions. Repetition alone is not
a blocking issue. Do not reverify paper facts, add user requirements or rewrite text.
For false, issues contains 1-8 objects with EXACT fields:
{"kind":"contradiction|scope_ambiguity","bindings":[{"claimId":"accepted ID",
"field":"text|conditions|executionSpec"}],"reason":"specific joint inconsistency"}.
Bind every involved existing answer field; one binding suffices for self-conflict.
No invented IDs, absent fields, excerpts or evidence transfers. Each reason is
1-600 characters. coherent=true REQUIRES issues=[]. The ordinary fixed-check rows
remain separate and unchanged. This consistency judgement grants no factual support.
'''


def identity(question, claims):
    keys=('claimId','kind','text','conditions','executionSpec','evidenceRefs','obligationIds')
    return digest({'question':str(question),'claims':[{k:c[k] for k in keys if k in c} for c in claims]})


def extract(rows, question, claims):
    value={'contractVersion':1,'status':'invalid_response','answerDigest':identity(question,claims)}
    if not isinstance(rows,list):return rows,value
    found=[r for r in rows if isinstance(r,dict) and r.get('auditType')=='answer_coherence']
    ordinary=[r for r in rows if not (isinstance(r,dict) and r.get('auditType')=='answer_coherence')]
    if len(found)!=1:return ordinary,value
    row=found[0]
    if (set(row)!={'auditType','coherent','issues'} or type(row['coherent']) is not bool
            or not isinstance(row['issues'],list) or len(row['issues'])>8
            or bool(row['issues'])==row['coherent']):return ordinary,value
    known={c['claimId']:c for c in claims}
    if len(known)!=len(claims):return ordinary,value
    for issue in row['issues']:
        if (not isinstance(issue,dict) or set(issue)!={'kind','bindings','reason'}
                or issue['kind'] not in ('contradiction','scope_ambiguity')
                or not isinstance(issue['reason'],str) or not 1<=len(issue['reason'].strip())<=600
                or not isinstance(issue['bindings'],list) or not 1<=len(issue['bindings'])<=8):return ordinary,value
        seen=set()
        for binding in issue['bindings']:
            if (not isinstance(binding,dict) or set(binding)!={'claimId','field'}
                    or not isinstance(binding.get('claimId'),str) or binding['claimId'] not in known
                    or binding.get('field') not in ('text','conditions','executionSpec')):return ordinary,value
            key=(binding['claimId'],binding['field']);field=known[binding['claimId']].get(binding['field'])
            if key in seen or not (isinstance(field,str) and field.strip() or isinstance(field,dict) and field):return ordinary,value
            seen.add(key)
    return ordinary,{**value,'status':'checked','coherent':row['coherent'],'issues':deepcopy(row['issues'])}


def revalidate(audit, question, claims):
    value=audit.get('answerCoherence',{})
    valid=(isinstance(value,dict) and value.get('contractVersion')==1
           and type(value.get('contractVersion')) is int and value.get('answerDigest')==identity(question,claims))
    if valid and value.get('status')=='checked':
        _,checked=extract([{'auditType':'answer_coherence','coherent':value.get('coherent'),
                            'issues':value.get('issues')}],question,claims)
        valid=checked['status']=='checked'
    else:valid=False
    if not valid:
        status=(value.get('status') if isinstance(value,dict) and value.get('answerDigest')==identity(question,claims)
                and value.get('status') in ('not_checked','invalid_response') else 'invalidated' if value else 'not_checked')
        value={'contractVersion':1,'status':status,
               'answerDigest':identity(question,claims)}
    gaps=[g for g in audit.get('gaps',[]) if not isinstance(g,dict) or not g.get('coherenceGap')]
    if not valid or value.get('coherent') is not True:
        gaps.append({'obligationId':audit.get('wholeQuestionId') or 'answer_coherence',
            'question':str(question),'stage':'answer','coherenceGap':True,
            'missingEvidence':'回答前后的一致性尚未确认' if not valid else '回答存在需统一的前后表述',
            'missingAspects':['核对并统一合并答案的表述范围']})
    result={**audit,'answerCoherence':value,'gaps':gaps}
    if not valid and result.get('status')=='checked':
        result['status']='invalid_response'  # Missing audit metadata is not a reason to rewrite verified facts.
    return result
