"""Verify source facts and non-entailment as separate, budgeted operations."""
from copy import deepcopy
import hashlib
import json

from services.deep_research.contracts import DeepResearchError
from services.deep_research.scope_expression_review import validate


def enabled(record):
    return (type(record.get('scopeExpressionReviewContractVersion')) is int
            and record['scopeExpressionReviewContractVersion'] in (2,3))


def assertions_enabled(record):
    version=record.get('scopeObservationContractVersion')
    return (2 if version==2 else True) if type(version) is int and version in (1,2) else False


def consistent_premises_enabled(record):
    return (type(record.get('scopeExpressionReviewContractVersion')) is int
            and record['scopeExpressionReviewContractVersion']==3)


def observation_claims(claim, expression, *, assertions=False, literal=False):
    """Literal projections of the authored settings, never inferred facts."""
    identity = [claim['claimId'], expression]
    if literal: identity.append('literal-setting-assertion-v2')
    if assertions: identity.append('observed-setting-assertion-v1')
    namespace = hashlib.sha256(json.dumps(identity,
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return [{**deepcopy(claim), 'claimId':f'scope-observation-{namespace}-{index}',
             'kind':'reported', 'text':('所引来源描述：'+setting['subject']+'，'+setting['attribute']+'为'+setting['value']+'。') if literal else ('所引来源报告，在对'+setting['subject']+'的一项评估中，'
                +setting['attribute']+'为'+setting['value']+'。') if assertions else
                setting['subject']+'，'+setting['attribute']+'='+setting['value'],
             'conditions':{}}
            for index, setting in enumerate(expression['observedSettings'])]


def review(checker, claim, expression, evidence, node):
    """Aggregate only complete factual checks and explicit entailment verdicts.

    The original whole-claim hard checks remain upstream. Observations receive
    the ordinary semantic/scope/attribution checks; epistemic operators receive
    a separate entailment task. No failed whole-claim verdict is upgraded.
    """
    policy = checker._scope_observation_assertions
    policy = policy() if callable(policy) else policy
    literal = type(policy) is int and policy==2
    assertions = policy is True or literal
    observations = observation_claims(claim, expression, assertions=assertions,literal=literal)
    checked = checker._check(observations, evidence, [], node) if observations else []
    expected = [c['claimId'] for c in observations]
    if ([c.get('claimId') for c in checked] != expected
            or any(c.get('status') not in ('passed','failed') for c in checked)):
        raise DeepResearchError('invalid_verification_response','观察条件核查未完整返回。')
    audit = {'version':2, 'observedSettings':checked, 'notEstablished':[],
             **({'observationContractVersion':2 if literal else 1} if assertions else {})}
    failed = [c for c in checked if c['status'] != 'passed']
    if failed:
        return {'claimId':claim['claimId'], 'status':'failed',
                'reason':'观察条件尚未通过事实核查：'+str(failed[0].get('reason','')),
                'partitionedScopeAudit':audit,
                **{k:failed[0][k] for k in ('executionState','reviewTimeAdmission','reviewInputCapacity') if k in failed[0]}}
    if not expression['notEstablished']:
        return {'claimId':claim['claimId'], 'status':'passed', 'reason':'全部观察条件已分别核查。',
                'partitionedScopeAudit':audit}

    from services.deep_research.verification_aliases import encode_verification_inputs, restore_verdict_evidence
    from services.deep_research.selection import surrounding_context
    _, wire, reverse = encode_verification_inputs([claim], evidence)
    own = [{k:deepcopy(e[k]) for k in ('evidenceId','quote','sourceWorkId','sourceVersionId',
                                     'sourceTitle','accessLevel','location','conditions','tableData',
                                     'sourcePublicationIdentity') if k in e}
           | {'sourceContext':surrounding_context(e)} for e in wire]
    if {reverse.get(e['evidenceId'],e['evidenceId']) for e in own} != set(claim['evidenceRefs']):
        return {'claimId':claim['claimId'],'status':'failed','reason':'推广命题的自身引用未完整提供。',
                'partitionedScopeAudit':audit}
    policy=checker._consistent_scope_premises
    consistent_premises=(policy() if callable(policy) else policy) is True
    prompt='''Review evidence ENTAILMENT, not whether the paper performed an experiment.
Each target is intended as a positive proposition P under the explicit authored operator
"THESE CITATIONS DO NOT ESTABLISH P". Decide whether the supplied passages and
their context entail P. Do not treat this operator as "P is false" or "authors
never tested P". No author-written disclaimer is required. Original source facts
are checked independently; their audit is not evidence for this task.
Check every substantive clause, comparison subject/domain and quantifier in P.
Do not insert universal quantifiers, weaken P, or use facts from outside the
supplied citations. A universal theorem or broader reported result can entail P;
do not manufacture uncertainty by ignoring it. Ambiguous quantification or
comparison scope is undetermined. Specific observations alone do not establish
a universal guarantee. A cherry-picked quotation cannot conceal contrary context.
Independently classify P's actual polarity: isNegation=true if P itself asserts a
negative conclusion, and authorOmission=true if P claims authors omitted tests.
Do not mark these false simply because a target was intended to be positive.
Return ONLY a JSON array in target order, exactly one object per proposition:
{"index":0,"proposition":"EXACT authored P","relation":"entailed|not_entailed|undetermined",
 "quantification":"explicit|ambiguous","isNegation":true or false,"authorOmission":true or false,
 "reason":"explain actual entailment or scope gap","premises":[{"evidenceId":"own E ID","path":["quote"]}]}
Premises must bind actual supplied source fields; permitted paths are ["quote"],
["sourceContext","before"] or ["sourceContext","after"], with a nonempty string.
Alternatively use evidenceId+quote with an exact contiguous original excerpt.
Never splice discontinuous excerpts. Every proposition requires its own premises.
The service decides acceptance; return your actual relation even if it rejects the boundary.
Targets:
'''+json.dumps(expression['notEstablished'],ensure_ascii=False,separators=(',',':'))+'\nEvidence:\n'+json.dumps(own,ensure_ascii=False,separators=(',',':'))
    if consistent_premises:
        prompt+='\nPrefer one source binding form per premise. If both path and quote are returned, the quote must be a contiguous excerpt of that exact visible field of the same evidenceId; both are checked. Extra fields, conflicting text and cross-field matches fail.\n'
    from services.deep_research.tools import TrackedLLMInvoker
    limit = checker._invoke.prompt_byte_limit(checker._run_id,node) if isinstance(checker._invoke,TrackedLLMInvoker) else 24000
    mechanism=getattr(checker,'_mechanism_grounding',False)
    if (mechanism() if callable(mechanism) else mechanism) is True:
        from services.deep_research.mechanism_grounding import GUIDANCE
        prompt+='\n'+GUIDANCE
    if len(prompt.encode()) > limit:
        raise DeepResearchError('scope_review_capacity','推广命题核查的完整原文超过输入容量，未发送。')
    from services.deep_research.factual_review import OPTION
    bounded = checker._bounded_factual_review
    bounded = (bounded() if callable(bounded) else bounded) is True
    result=checker._invoke(run_id=checker._run_id,node=node,prompt=prompt,
        extra_body={'max_tokens':4000,'temperature':0.0,**({OPTION:True} if bounded and node=='verify' else {})},use_reserve=True)
    if result.get('notStarted')=='factual_review_time_budget':
        return {'claimId':claim['claimId'],'status':'failed','reason':'剩余时间不足以完成推广命题核查。',
                'executionState':'not_started','reviewTimeAdmission':result['admission'],'partitionedScopeAudit':audit}
    from services.deep_research.graph import _safe_parse_json
    rows=_safe_parse_json(result.get('content',''))
    keys={'index','proposition','relation','quantification','isNegation','authorOmission','reason','premises'}
    if (result.get('finishReason')=='length' or not isinstance(rows,list)
            or len(rows)!=len(expression['notEstablished']) or any(not isinstance(r,dict) or set(r)!=keys for r in rows)):
        raise DeepResearchError('invalid_verification_response','推广命题核查未完整返回，不能据此确认结论。')
    restored=restore_verdict_evidence({'scopeExpressionAudit':{'observedSettings':[], 'notEstablished':rows}},
                                     reverse,scope_expression=True)
    audit['notEstablished']=restored['scopeExpressionAudit']['notEstablished']
    # Only the exact positive proposition with explicit scope and own premises
    # can establish non-entailment. Entailed/ambiguous/unknown results fail.
    errors=validate(claim,{'observedSettings':[], 'notEstablished':expression['notEstablished']},restored,
                    [{**e,'sourceContext':surrounding_context(e)} for e in evidence],
                    consistent_premises=consistent_premises)
    return {'claimId':claim['claimId'],'status':'failed' if errors else 'passed',
            'reason':'推广命题尚未核实：'+', '.join(errors) if errors else '观察条件与证据推导边界已分别核查。',
            'partitionedScopeAudit':audit}
