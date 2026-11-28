"""Verify source facts and non-entailment as separate, budgeted operations."""
from copy import deepcopy
import hashlib
import json

from services.deep_research.contracts import DeepResearchError
from services.deep_research.scope_expression_review import validate


def enabled(record):
    return (type(record.get('scopeExpressionReviewContractVersion')) is int
            and record['scopeExpressionReviewContractVersion'] in (2,3,4,5,6))


def assertions_enabled(record):
    version=record.get('scopeObservationContractVersion')
    return (version if version>=2 else True) if type(version) is int and version in (1,2,3,4,5) else False


def consistent_premises_enabled(record):
    return (type(record.get('scopeExpressionReviewContractVersion')) is int
            and record['scopeExpressionReviewContractVersion'] in (3,4,5,6))


def short_circuit_enabled(record):
    return (type(record.get('scopeExpressionReviewContractVersion')) is int
            and record['scopeExpressionReviewContractVersion'] in (4,5,6))


def focused_boundary_policy(record):
    version = record.get('scopeExpressionReviewContractVersion')
    return version if type(version) is int and version in (5, 6) else False


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
    atomic_comparison = type(policy) is int and policy in (3, 4, 5)
    literal = type(policy) is int and policy in (2, 3, 4, 5)
    assertions = policy is True or literal
    observations = observation_claims(claim, expression, assertions=assertions,literal=literal)
    review_options = {'scope_observations': True} if atomic_comparison else {}
    observation_metadata = {'observationContractVersion': policy if literal else 1} if assertions else {}

    def wire_targets(targets):
        ids = {f'O{index + 1}': target['claimId'] for index, target in enumerate(targets)}
        return [{**target, 'claimId': alias} for alias, target in zip(ids, targets)], ids

    def check_observations(targets):
        if policy not in (4, 5):
            return checker._check(targets, evidence, [], node, **review_options)
        # The reviewer copies short request-local IDs. Keep the full identity
        # for the parent assertion and every persisted observation audit.
        wire, ids = wire_targets(targets)
        checked = checker._check(wire, evidence, [], node, **review_options)
        if any(row.get('claimId') not in ids for row in checked):
            raise DeepResearchError('invalid_verification_response', '观察条件核查编号无效。')
        return [{**row, 'claimId': ids[row['claimId']]} for row in checked]

    failure_policy=getattr(checker,'_known_single_review_failure',False)
    failure_policy=(failure_policy() if callable(failure_policy) else failure_policy) is True
    isolation=checker._isolate_factual_claims
    isolation=(isolation() if callable(isolation) else isolation) is True
    short_circuit=getattr(checker,'_short_circuit_scope_observations',False)
    short_circuit=(short_circuit() if callable(short_circuit) else short_circuit) is True
    if (failure_policy or short_circuit) and isolation:
        from services.deep_research.review_response_failure import invalid as invalid_response
        batches = [[observation] for observation in observations]
        batch_policy = getattr(checker, '_comparison_review_batches', False)
        batch_policy = batch_policy() if callable(batch_policy) else batch_policy
        if policy == 5 and batch_policy is True:
            from services.deep_research.comparison_review_batches import groups
            batches = groups(observations, lambda targets: checker._check_batch(
                wire_targets(targets)[0], evidence, [], node=node, _preview=True, **review_options))
        checked=[]
        for batch in batches:
            rows=check_observations(batch)
            if ([row.get('claimId') for row in rows] != [target['claimId'] for target in batch]
                    or any(row.get('status') not in ('passed','failed') for row in rows)):
                raise DeepResearchError('invalid_verification_response','观察条件核查未完整返回。')
            checked.extend(rows)
            unresolved = next((row for row in rows if invalid_response(row.get('reviewResponseAudit'))
                              or short_circuit and row['status']=='failed'), None)
            if unresolved is None:
                continue
            remaining = observations[len(checked):]
            if invalid_response(unresolved.get('reviewResponseAudit')):
                audit={'version':2,'observedSettings':checked,'notEstablished':[],
                    'unreviewedObservationIds':[c['claimId'] for c in remaining],
                    **observation_metadata}
                if short_circuit:
                    audit.update(observationSchedulingVersion=1,
                        stoppedAfterObservationId=batch[-1]['claimId'],
                        unreviewedPropositionCount=len(expression['notEstablished']))
                response_audit=deepcopy(unresolved['reviewResponseAudit'])
                response_audit['unreviewedObservationCount']=len(remaining)
                return {'claimId':claim['claimId'],'status':'failed','reason':unresolved['reason'],
                    'executionState':'received_invalid','reviewResponseAudit':response_audit,
                    'partitionedScopeAudit':audit}
            if short_circuit:
                audit={'version':2,'observedSettings':checked,'notEstablished':[],
                    'observationSchedulingVersion':1,
                    'stoppedAfterObservationId':batch[-1]['claimId'],
                    'unreviewedObservationIds':[c['claimId'] for c in remaining],
                    'unreviewedPropositionCount':len(expression['notEstablished']),
                    **observation_metadata}
                return {'claimId':claim['claimId'],'status':'failed',
                    'reason':'观察条件尚未通过事实核查：'+str(unresolved.get('reason','')),
                    'partitionedScopeAudit':audit,
                    **{k:unresolved[k] for k in ('executionState','reviewTimeAdmission','reviewInputCapacity',
                        'reviewDiagnosticAudit','reviewResponseAudit') if k in unresolved}}
    else:
        checked = check_observations(observations) if observations else []
    expected = [c['claimId'] for c in observations]
    if ([c.get('claimId') for c in checked] != expected
            or any(c.get('status') not in ('passed','failed') for c in checked)):
        raise DeepResearchError('invalid_verification_response','观察条件核查未完整返回。')
    audit = {'version':2, 'observedSettings':checked, 'notEstablished':[],
             **observation_metadata}
    failed = [c for c in checked if c['status'] != 'passed']
    if failed:
        return {'claimId':claim['claimId'], 'status':'failed',
                'reason':'观察条件尚未通过事实核查：'+str(failed[0].get('reason','')),
                'partitionedScopeAudit':audit,
                **{k:failed[0][k] for k in ('executionState','reviewTimeAdmission','reviewInputCapacity','reviewDiagnosticAudit','reviewResponseAudit') if k in failed[0]}}
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
    diagnostics=getattr(checker,'_review_diagnostic_bindings',False)
    diagnostics=(diagnostics() if callable(diagnostics) else diagnostics) is True
    policy = getattr(checker, '_focused_boundary_review', False)
    policy = policy() if callable(policy) else policy
    focused = policy is True or policy in (5, 6)
    if diagnostics:
        from services.deep_research.review_diagnostics import GUIDANCE as diagnostic_guidance
        prompt+='\n'+diagnostic_guidance
    if focused:
        from services.deep_research.review_source_fields import visible_paths
        paths = {row['evidenceId']: visible_paths(row) for row in own}
        prompt = prompt.replace('permitted paths are ["quote"],\n["sourceContext","before"] or ["sourceContext","after"], with a nonempty string.',
                                'use only the available premise paths listed below for that evidence ID.', 1)
        prompt += ('\nFor this entailment check, give one short reason naming the decisive condition or clause. '
                   'For not_entailed, identify the missing link in these citations. Do not add incidental '
                   'reported values, hardware models, or alternative numerical results. Include a measured '
                   'value only where it is necessary to decide the proposition. Never use titles or section '
                   'labels in the context as measurement evidence. Copy an available premise path from '
                   'the same evidence ID, including ["sourceContext"] when listed for scalar context. '
                   'Available premise paths:\n' + json.dumps(paths, ensure_ascii=False, separators=(',', ':')))
        if diagnostics:
            prompt += ('\nIf the reason adds no positive source fact, return diagnosticFacts: []. '
                       'For each necessary new source fact, copy the exact statement from your final reason '
                       'and the contiguous original excerpt from the specified field of its own evidence.')
            if policy == 6:
                prompt += (' Use "the compared measurements" or "the cited results" in your reason '
                           'without counting them. State the specific missing condition. '
                           'A number remains appropriate only when it is needed to decide the proposition '
                           'and is present in the target or bound to original evidence.')
    from services.deep_research.tools import TrackedLLMInvoker
    limit = checker._invoke.prompt_byte_limit(checker._run_id,node) if isinstance(checker._invoke,TrackedLLMInvoker) else 24000
    mechanism=getattr(checker,'_mechanism_grounding',False)
    from services.deep_research.mechanism_grounding import guidance as mechanism_instructions
    mechanism=mechanism_instructions(mechanism() if callable(mechanism) else mechanism)
    if mechanism:
        prompt+='\n'+mechanism
    if len(prompt.encode()) > limit:
        raise DeepResearchError('scope_review_capacity','推广命题核查的完整原文超过输入容量，未发送。')
    from services.deep_research.factual_review import DIRECT_REVIEW_OPTION, OPTION, REPAIR_OUTPUT_OPTION
    bounded = checker._bounded_factual_review
    bounded = (bounded() if callable(bounded) else bounded) is True
    policy = getattr(checker, '_direct_comparison_scope_review', False)
    direct = (policy() if callable(policy) else policy) is True
    if direct and node in ('verify', 'verify_repair'):
        options = {DIRECT_REVIEW_OPTION if node == 'verify' else REPAIR_OUTPUT_OPTION: True}
    else:
        options = {OPTION: True} if bounded and node == 'verify' else {}
    result=checker._invoke(run_id=checker._run_id,node=node,prompt=prompt,
        extra_body={'max_tokens':4000,'temperature':0.0,**options},use_reserve=True)
    if result.get('notStarted')=='factual_review_time_budget':
        return {'claimId':claim['claimId'],'status':'failed','reason':'剩余时间不足以完成推广命题核查。',
                'executionState':'not_started','reviewTimeAdmission':result['admission'],'partitionedScopeAudit':audit}
    from services.deep_research.graph import _safe_parse_json
    rows=_safe_parse_json(result.get('content',''))
    keys={'index','proposition','relation','quantification','isNegation','authorOmission','reason','premises'}
    if diagnostics:keys.add('diagnosticFacts')
    if (result.get('finishReason')=='length' or not isinstance(rows,list)
            or len(rows)!=len(expression['notEstablished']) or any(not isinstance(r,dict)
                or (set(r)!=keys and not (diagnostics and set(r)==keys-{'diagnosticFacts'})) for r in rows)):
        from services.deep_research.review_response_failure import eligible as isolate_invalid, unresolved
        policy=getattr(checker,'_known_single_review_failure',False)
        policy=(policy() if callable(policy) else policy) is True
        isolation=checker._isolate_factual_claims
        isolation=(isolation() if callable(isolation) else isolation) is True
        error=DeepResearchError('invalid_verification_response','推广命题核查未完整返回，不能据此确认结论。',
            {'responseState':'received_invalid'} if policy else None)
        if isolate_invalid(policy,isolation,[claim],result,error,node):
            return {**unresolved(claim,result),'partitionedScopeAudit':audit}
        raise error
    restored=restore_verdict_evidence({'scopeExpressionAudit':{'observedSettings':[], 'notEstablished':rows}},
                                     reverse,scope_expression=True)
    audit['notEstablished']=restored['scopeExpressionAudit']['notEstablished']
    if focused:
        review_evidence = [{**row, 'evidenceId': reverse.get(row['evidenceId'], row['evidenceId'])} for row in own]
    else:
        review_evidence = [{**e, 'sourceContext': surrounding_context(e)} for e in evidence]
    if diagnostics:
        from services.deep_research.review_diagnostics import bind as bind_diagnostic, parameter_options
        parameter_policy=getattr(checker,'_diagnostic_parameter_ids',False)
        parameter_policy=parameter_policy() if callable(parameter_policy) else parameter_policy
        # The count of the compared papers comes from the visible citation
        # packet and provides no evidence about experimental measurements.
        cited_works = {row.get('sourceWorkId') for row in own}
        cited_paper_pair = (parameter_policy in (6, 7) and len(cited_works) == 2
                            and all(row.get('sourceWorkId') and row.get('sourceVersionId')
                                    and row.get('accessLevel') == 'fulltext' for row in own))
        # Operator inputs are typed propositions, not the original target prose.
        # Their unseen prose cannot authorize structural navigation exemptions.
        diagnostic_checks=[bind_diagnostic({'status':'passed' if row['relation']=='not_entailed' else 'failed',
            'reason':row['reason'],'diagnosticFacts':row.get('diagnosticFacts')},claim,
            review_evidence,reverse,cited_paper_pair=cited_paper_pair,
            **parameter_options(parameter_policy)) for row in rows]
        invalid=next((v for v in diagnostic_checks if v['reviewDiagnosticAudit']['errors']),None)
        if invalid:
            return {'claimId':claim['claimId'],'status':'failed','reason':invalid['reason'],
                'executionState':'received_invalid','reviewDiagnosticAudit':invalid['reviewDiagnosticAudit'],
                'partitionedScopeAudit':audit}
    # Only the exact positive proposition with explicit scope and own premises
    # can establish non-entailment. Entailed/ambiguous/unknown results fail.
    errors=validate(claim,{'observedSettings':[], 'notEstablished':expression['notEstablished']},restored,
                    review_evidence,
                    consistent_premises=consistent_premises)
    return {'claimId':claim['claimId'],'status':'failed' if errors else 'passed',
            'reason':'推广命题尚未核实：'+', '.join(errors) if errors else '观察条件与证据推导边界已分别核查。',
            'partitionedScopeAudit':audit}
