"""A bounded final-answer audit, distinct from retrieval and factual verification."""
import json

from services.deep_research.contracts import BudgetExhaustedError


def coverage_prompt_byte_limit(budget):
    """Fit to currently available finalization capacity; admission stays atomic."""
    if not budget or 'maxTokens' not in budget:
        return 24000
    keys = ('maxTokens', 'tokens', 'reserveTokens', 'normalTokens',
            'maxModelCalls', 'modelCalls', 'reserveModelCalls', 'reservedModelCalls')
    if any(type(budget.get(k, 0)) is not int or budget.get(k, 0) < 0 for k in keys):
        return 0
    maximum, used, reserve, normal, calls, ordinary, reserved, final = [budget.get(k, 0) for k in keys]
    if reserve > maximum or reserved > calls or ordinary + final >= calls:
        return 0
    remaining = maximum - used
    if final >= reserved:
        if ordinary >= calls - reserved:
            return 0
        remaining = min(remaining, maximum - reserve - normal)
    return max(0, min(24000, remaining - 3500 - 1024))


def audit_final_answer(run_id, question, plan, claims, evidence, invoke, parse, *, budget=None):
    from services.deep_research.answer_coverage import answer_coverage_gaps
    from services.deep_research.selection import balanced_sample, surrounding_context

    # A plan can itself omit part of the request. Audit the original question as
    # well as each planned obligation, without changing the stored research plan.
    from services.deep_research.obligation_purpose import normalize_obligation_purposes, nonblocking_research_obligations
    audit_plan = normalize_obligation_purposes(plan, question)
    identity = None
    if plan and question:
        known = {o['obligationId'] for p in plan for o in p.get('obligations', [])}
        identity = 'answer_scope'
        while identity in known:
            identity += '_'
        audit_plan.append({'obligations': [{'obligationId': identity, 'question': question}]})
    verdicts = []
    status = 'not_checked'
    invalid_aspects = []
    criterion_gaps = {}
    invalid_criteria = []
    nonblocking = []
    budget_limit = None
    if claims and plan and invoke:
        cited = {ref for claim in claims for ref in claim.get('evidenceRefs', [])}
        selected = balanced_sample(sorted(evidence, key=lambda e: e.get('evidenceId') not in cited),
            lambda e: (e.get('sourceWorkId'), tuple(e.get('obligationIds', []))), 20)
        from uuid import uuid4
        from services.deep_research.prompt_budget import fit_evidence_prompt
        from services.deep_research.verification_aliases import (
            encode_verification_inputs, restore_visible_evidence, restore_coverage_evidence)
        # The audit can inspect uncited passages for omitted conditions; these
        # aliases shorten identities without changing any claim's citations.
        wire_claims, selected, reverse_aliases = encode_verification_inputs(
            [*claims, {'evidenceRefs': [e['evidenceId'] for e in selected]}], selected)
        wire_claims = wire_claims[:-1]
        evidence_marker = uuid4().hex
        rows = [{
            'evidenceId': e['evidenceId'], 'quote': e.get('quote', ''),
            'sourceContext': surrounding_context(e), 'source': e.get('sourceWorkId'),
            'conditions': e.get('conditions', {}),
            'accessLevel': e.get('accessLevel'),
        } for e in selected]
        from services.deep_research.execution_materialization import verification_claim_view
        # Remove only the exact generated suffix, retaining original prose,
        # conditions and all typed values. The audit still sees the full answer;
        # duplicated display text is reproducible from executionSpec.
        wire_claims = [verification_claim_view(c) for c in wire_claims]
        wire_obligations = []
        for item in audit_plan:
            for obligation in item.get('obligations', []):
                # Queries guide acquisition, not final-answer requirements.
                # Exact repeated user text is referenced, never abbreviated.
                row = {key: value for key, value in obligation.items() if key != 'searchQuery'}
                for field in ('question', 'requestExcerpt'):
                    if row.get(field) == question:
                        row[field + 'Ref'] = 'userQuestion'
                        del row[field]
                wire_obligations.append(row)
        from services.deep_research.coverage_policy import FINAL_COVERAGE_POLICY
        prompt = f'''Audit whether the FINAL ACCEPTED ANSWER fully answers the user's question.
Question: {question}
Research and answer obligations (including the original question): {json.dumps(wire_obligations, ensure_ascii=False, separators=(',', ':'))}
Accepted final claims: {json.dumps(wire_claims, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}
Available evidence for detecting omitted conditions: {evidence_marker}

{FINAL_COVERAGE_POLICY}
In input obligations, questionRef/requestExcerptRef="userQuestion" resolves to the
EXACT full Question above. Return literal excerpts, never the reference label.
Return only a JSON array, exactly one entry for each of these obligationIds,
including the original-question scope: {json.dumps([o['obligationId'] for p in audit_plan for o in p.get('obligations', [])])}'''
        criterion_shape = {o['obligationId']: [
            {'criterionId': c['criterionId'], 'responseType': c['responseType'],
             'status': 'covered|partial|missing', 'bindings': []} for c in o['completionCriteria']]
            for item in audit_plan for o in item.get('obligations', []) if o.get('completionCriteria')}
        if criterion_shape:
            prompt += '\nReturn BOTH aspects and criteria. Copy the following fixed criterion identities into each corresponding obligation object. '
            prompt += 'Replace each status with one actual verdict and supply only valid answer bindings; do not omit or rename criterionIds. '
            prompt += 'Obligations absent from this map do not require criteria.\nRequired criterion fields by obligation: '
            prompt += json.dumps(criterion_shape, ensure_ascii=False, separators=(',', ':'))
        template = prompt
        try:
            limit = coverage_prompt_byte_limit(budget)
            render = lambda selected_rows: template.replace(evidence_marker, json.dumps(selected_rows, ensure_ascii=False, separators=(',', ':')), 1)
            fixed_bytes = len(render([]).encode('utf-8'))
            if limit <= 0 or fixed_bytes > limit:
                raise BudgetExhaustedError('coveragePromptBytes', limit, fixed_bytes)
            prompt, rows = fit_evidence_prompt(rows, render, max_bytes=limit)
            result = invoke(run_id, 'verify_answer_coverage', prompt,
                            {'max_tokens': 3500, 'temperature': 0.0}, use_reserve=True)
            content = result.get('content', '') if isinstance(result, dict) else getattr(result, 'content', '')
            finish = result.get('finishReason', result.get('finish_reason')) if isinstance(result, dict) else getattr(result, 'finish_reason', None)
            try:
                verdicts = parse(content) if finish != 'length' else None
            except (ValueError, TypeError):
                verdicts = None
            status = 'checked' if isinstance(verdicts, list) else 'invalid_response'
            if isinstance(verdicts, list):
                verdicts = restore_coverage_evidence(verdicts, reverse_aliases)
                rows = restore_visible_evidence(rows, reverse_aliases)
                from services.deep_research.coverage_references import resolve_coverage_references
                verdicts = resolve_coverage_references(verdicts, claims, rows)
                from services.deep_research.completion_criteria import completion_criteria_gaps, invalid_criterion_reviews
                invalid_criteria = invalid_criterion_reviews(audit_plan, claims, verdicts)
                if invalid_criteria:
                    status = 'invalid_response'
                criterion_gaps = completion_criteria_gaps(audit_plan, claims, verdicts)
                verdicts = [{**v, 'status': 'partial'} if isinstance(v, dict)
                    and v.get('obligationId') in criterion_gaps else v for v in verdicts]
                # Explicitly reported missing subrequirements override an
                # inconsistent overall "covered", and remain repairable gaps.
                verdicts = [{**v, 'status': 'partial'} if isinstance(v, dict)
                    and v.get('status') == 'covered' and isinstance(v.get('aspects'), list)
                    and any(isinstance(a, dict) and a.get('status') in {'partial', 'missing'}
                            for a in v['aspects']) else v for v in verdicts]
                from services.deep_research.coverage_aspects import invalid_coverage_aspects
                invalid_aspects = invalid_coverage_aspects(verdicts, claims, rows,
                    [question, *[o.get('question', '') for p in audit_plan for o in p.get('obligations', [])]],
                    request_only_obligations=[identity] if identity else [])
                if invalid_aspects:
                    verdicts = [{**v, 'status': 'partial'} if isinstance(v, dict)
                        and v.get('obligationId') in invalid_aspects else v for v in verdicts]
                    status = 'invalid_response'
        except BudgetExhaustedError as exc:
            # Publish only supported text with an explicit coverage gap. Never
            # promote budget exhaustion to a complete answer or add a retry.
            status = 'budget_exhausted'
            budget_limit = exc.details
    if status == 'checked' and identity:
        nonblocking = nonblocking_research_obligations(plan, question, claims, verdicts,
                                                     identity, invalid_aspects)
    excluded = {row['obligationId'] for row in nonblocking}
    effective_plan = [{**item, 'obligations': [o for o in item.get('obligations', [])
                      if o.get('obligationId') not in excluded]} for item in audit_plan]
    gaps = answer_coverage_gaps(effective_plan, claims, verdicts)
    for gap in gaps:
        matching = [v for v in verdicts if isinstance(v, dict)
                    and v.get('obligationId') == gap.get('obligationId')] if isinstance(verdicts, list) else []
        if len(matching) == 1 and isinstance(matching[0].get('aspects'), list):
            gap['missingAspects'] = list(dict.fromkeys(a['requirement'].strip()
                for a in matching[0]['aspects'] if isinstance(a, dict)
                and a.get('status') in {'partial', 'missing'}
                and isinstance(a.get('requirement'), str) and a['requirement'].strip()))
            gap['aspectEvidenceRefs'] = list(dict.fromkeys(a['basis']['evidenceId']
                for a in matching[0]['aspects'] if isinstance(a, dict)
                and a.get('status') in {'partial', 'missing'}
                and isinstance(a.get('basis'), dict) and a['basis'].get('kind') == 'source'
                and isinstance(a['basis'].get('evidenceId'), str)))
        if gap.get('obligationId') in criterion_gaps:
            gap['missingAspects'] = list(dict.fromkeys([
                *gap.get('missingAspects', []), *criterion_gaps[gap['obligationId']]]))
        if status in {'budget_exhausted', 'invalid_response'}:
            gap['missingEvidence'] = '回答完整性尚未核验'
            gap['auditStatus'] = status
        if identity and gap.get('obligationId') == identity:
            gap['wholeQuestion'] = True
    from services.deep_research.completion_criteria import completion_contract_digest
    return {'status': status, 'verdicts': verdicts if isinstance(verdicts, list) else [],
            'completionContractDigest': completion_contract_digest(plan, claims),
            'gaps': gaps, 'invalidAspectObligations': invalid_aspects,
            'wholeQuestionId': identity, 'nonblockingResearch': nonblocking,
            'criterionGaps': criterion_gaps,
            'invalidCriterionObligations': invalid_criteria,
            'budgetLimit': budget_limit}


def remaining_retrieval_gaps(gaps, audit, claims, evidence, *, plan=None, question=""):
    """Return source gaps that still block the actual answer.

    Required research keeps the source-specific closure rule: a bounded factual
    answer may close it, never another paper's answer or an unchecked proposal.
    Separately audited unnecessary support questions are nonblocking, not solved;
    callers retain the untouched original gap list in the run's research history.
    """
    if audit.get('status') != 'checked':
        return list(gaps)
    # Revalidate against current accepted claims; a stored exemption list alone
    # is never enough, and the original source gaps remain in run history.
    from services.deep_research.obligation_purpose import nonblocking_research_obligations
    optional = nonblocking_research_obligations(plan, question, claims,
        audit.get('verdicts'), audit.get('wholeQuestionId'), audit.get('invalidAspectObligations', []))
    optional_ids = {row['obligationId'] for row in optional}
    gaps = [gap for gap in gaps if not isinstance(gap, dict) or gap.get('obligationId') not in optional_ids]
    missing = {g.get('obligationId') for g in audit.get('gaps', [])}
    from services.deep_research.answer_coverage import answer_coverage_gaps
    check_plan = [{'obligations': [g for g in gaps if isinstance(g, dict) and g.get('obligationId')]}]
    missing.update(g.get('obligationId') for g in answer_coverage_gaps(check_plan, claims, audit.get('verdicts')))
    accepted = {c.get('claimId'): c for c in claims
                if c.get('verification') == 'semantic_passed' and c.get('kind') in {'reported', 'inference'}}
    origins = {e.get('evidenceId'): e.get('sourceWorkId') for e in evidence
               if e.get('verification', {}).get('literal') == 'passed'}
    covered = {}
    for verdict in audit.get('verdicts', []):
        oid = verdict.get('obligationId')
        if verdict.get('status') != 'covered' or oid in missing:
            continue
        works = set()
        for binding in verdict.get('bindings', []):
            claim = accepted.get(binding.get('claimId'), {})
            works.update(origins[ref] for ref in claim.get('evidenceRefs', []) if origins.get(ref))
        covered[oid] = works
    return [gap for gap in gaps if not isinstance(gap, dict)
            or gap.get('sourceWorkId') not in covered.get(gap.get('obligationId'), set())]
