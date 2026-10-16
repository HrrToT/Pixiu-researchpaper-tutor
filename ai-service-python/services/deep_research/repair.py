"""One bounded revision within the acquired source versions, followed by verification."""
from __future__ import annotations

import json
from copy import deepcopy

from services.deep_research.answer_constraints import answer_character_count, requested_character_limit, normalize_conditions, resolve_evidence_aliases
from services.deep_research.contracts import BudgetExhaustedError
from services.deep_research.selection import surrounding_context
from services.deep_research.prompt_budget import fit_evidence_prompt
from services.deep_research.synthesis import SCIENTIFIC_TERMINOLOGY
from uuid import uuid4
from services.deep_research.repair_scope import repair_evidence_scope


def _prepare_repair(report, verification, evidence, question, *, max_prompt_bytes=24000,
                    metric_domains=None, draft_context=()):
    rejected = {row['claimId']: row for row in verification.get('rejected', [])}
    originals = {row['claimId']: row for row in report.get('claims', []) if row.get('claimId') in rejected}
    if not originals:
        return []
    hinted = {ref for row in rejected.values() for ref in row.get('missingEvidenceRefs', [])
              if isinstance(ref, str)}
    evidence = sorted(evidence, key=lambda e: e.get('evidenceId') not in hinted)
    allowed = repair_evidence_scope(list(originals.values()), evidence)
    refs = {ref for values in allowed.values() for ref in values}
    selected = [e for e in evidence if e['evidenceId'] in refs]
    aliases = {f'E{i + 1}': e['evidenceId'] for i, e in enumerate(selected)}
    short_ids = {full: short for short, full in aliases.items()}
    original_refs = {ref for row in originals.values() for ref in row.get('evidenceRefs', [])}
    rows = [
        {key: value for key, value in {
         'evidenceId': short_ids[e['evidenceId']], 'quote': e.get('quote', ''),
         'sourceContext': surrounding_context(e), 'location': e.get('location', {}),
         'accessLevel': e.get('accessLevel'), 'conditions': e.get('conditions', {}),
         'tableData': e.get('tableData')}.items()
         if value is not None and value != {} and value != []}
        for e in sorted(selected, key=lambda e: (e['evidenceId'] not in hinted,
                                                 e['evidenceId'] not in original_refs))
    ]
    evidence_marker, permissions_marker = uuid4().hex, uuid4().hex
    input_claims = resolve_evidence_aliases({'claims': deepcopy(list(originals.values()))}, short_ids)['claims']
    from services.deep_research.execution_materialization import verification_claim_view
    def compact_claim_view(row):
        row = verification_claim_view(row)
        # Version stamps are controlled by originals/server, never repairable
        # choices. Keep every original prose/configuration field and avoid
        # encouraging the model to copy metadata into executionSpec.
        return {key: value for key, value in row.items()
                if key not in {'designContractVersion', 'budgetContractVersion', 'hypothesisContractVersion','protocolContractVersion','workflowContractVersion'}
                and not (key in {'conditions', 'obligationIds'} and value in ({}, []))}
    input_claims = [compact_claim_view(row) for row in input_claims]
    from services.deep_research.repair_prompt import factor_repair_questions, factor_design_deliverables
    question_dictionary, packed_checks = factor_repair_questions(rejected)
    if any(row.get('designContractVersion') == 2 for row in originals.values()):
        from services.deep_research.experimental_reasoning import DESIGN_ROLES
        packed_checks = factor_design_deliverables(packed_checks, originals.values(), DESIGN_ROLES)
    for check in packed_checks.values():
        if isinstance(check.get('missingEvidenceRefs'), list):
            check['missingEvidenceRefs'] = [short_ids.get(ref, ref) if isinstance(ref, str) else ref
                                            for ref in check['missingEvidenceRefs']]
    revision_shape = {'claimId': 'original ID', 'kind': 'original kind', 'text': 'revised wording',
                      'evidenceRefs': ['E1'], 'conditions': {}, 'detailLevel': 'fulltext'}
    has_tables = any(row.get('tableData') for row in rows) or any(
        row.get('tableBindings') for row in originals.values())
    if has_tables:
        revision_shape['tableBindings'] = [{'evidenceId': 'E1', 'rowNumber': 'actual integer',
            'groupIndex': 'actual zero-based integer', 'metric': 'exact header', 'value': 'exact string'}]
    if any(row.get('designContractVersion') == 2 for row in originals.values()):
        revision_shape.update(designRole='canonical role for proposals/hypotheses; omit for facts',
                              executionSpec='complete role-specific object for groups/data/analysis and versioned controls/budget/hypothesis; omit for other roles')
    proposal_context = [{key: row[key] for key in ('claimId', 'text', 'kind', 'conditions', 'designRole', 'executionSpec', 'designContractVersion', 'budgetContractVersion', 'hypothesisContractVersion','protocolContractVersion','workflowContractVersion') if key in row}
                        for row in verification.get('accepted', [])
                        if row.get('kind') in {'proposal', 'suggestion', 'hypothesis'}
                        and row.get('claimId') not in originals]
    proposal_context = [compact_claim_view(row) for row in proposal_context]
    sibling_context = [{key: value for key, value in compact_claim_view(row).items()
                        if key not in {'evidenceRefs', 'obligationIds', 'detailLevel', 'tableBindings'}} for row in draft_context
                       if row.get('claimId') not in originals
                       and row.get('kind') in {'proposal', 'suggestion', 'hypothesis'}]
    from services.deep_research.verification_context import CONFIG_ROLES, configuration_context
    if (all(row.get('designRole') in CONFIG_ROLES for row in originals.values())
            and any(row.get('protocolContractVersion') == 1 or row.get('workflowContractVersion') in (1, 2)
                    for row in originals.values())):
        # Versioned operational repairs need all operational definitions and
        # explicit dependencies, not unrelated scientific prose. Keep accepted
        # versus unverified sibling status separate, and never change storage.
        selected_context = configuration_context(list(originals.values()), [*proposal_context, *sibling_context])
        retained = {row['claimId'] for row in selected_context}
        proposal_context = [row for row in proposal_context if row['claimId'] in retained]
        sibling_context = [row for row in sibling_context if row['claimId'] in retained]
    prompt = f'''Revise only the targets; narrow unsupported wording or omit it.
answer_incomplete requires filling requested omissions, conditioning inputs and applicability,
not merely shortening. A missing mechanism explanation needs how/why the requested
input affects the operation/output, in ordinary words if requested for novices;
listing names or repeating a technical operation is not sufficient. Do not add
unsupported mechanics: use the allowed evidence or retain the limitation.
Equation/parameter-link deductions may be inference claims with explicit cited
premises and conditional effects; they do not establish guaranteed convergence.
If a central inference is supported but an appended list of mechanisms is not,
retain only the supported conclusion and premises. Do not replace unsupported
details with a paper-wide claim that those details were never measured.
absence_not_established requires bounded positive evidence:
missing passages do not prove paper-wide absence; finite results do not prove universality.
Question: {question}
Accepted experimental definitions (consistency only; do not revise these or treat them as paper evidence):
{json.dumps(proposal_context, ensure_ascii=False, separators=(',', ':'))}
Other draft definitions (UNVERIFIED consistency context, not frozen choices or paper evidence;
these may be revised in other batches; never return a verdict or revision for these IDs):
{json.dumps(sibling_context, ensure_ascii=False, separators=(',', ':'))}
Application-generated protocol suffixes are omitted here; their complete executionSpec remains.
The interface renders those fields. Preserve original prose consistency; do not duplicate that rendering.
Missing-question dictionary (each missingQuestionIds entry refers to the exact question here;
Q identifiers are internal references, never evidence or text to publish):
{json.dumps(question_dictionary, ensure_ascii=False, separators=(',', ':'))}
detailRequirementRole points to the identical required role definition under Experimental deliverables below.
Rejected claims and checks:
{json.dumps([{'claim': row, 'check': packed_checks[row['claimId']]} for row in input_claims], ensure_ascii=False, separators=(',', ':'))}
Allowed evidence IDs per claim (candidate permissions, not proof of support):
{permissions_marker}
Exact available evidence:
{evidence_marker}
missingEvidenceRefs are prioritized candidates, not guaranteed supplied passages.
Only the evidence actually listed above and in each claim's allowed IDs is usable.
Return a COMPACT JSON array, or [] if no supported revision is possible. Schema:
{json.dumps(revision_shape, ensure_ascii=False)}
Use actual values, not schema descriptions; wording key is "text".
Preserve claimId, kind and valid designRole; no new claims, searches or reported results.
Empty claims with missing_design_deliverable checks are server-allocated slots:
fill their required design content using these exact IDs, kinds and roles.
Never disguise a fact as a proposal. Retain necessary conditions and the user's length limit.
The limit covers ALL revised and accepted text plus conditions together, not each claim.
Write necessary conditions once in text and use conditions={{}} when already stated.
Drop secondary examples before the requested identities or explanation; do not switch
to another table/experiment merely because it contains the same number.
Each claim may cite ONLY its own allowed supplied evidence. Same-version permission and
obligation labels do not prove relevance or support. Check every factual clause.
For purely prospective choices or mathematical definitions, use evidenceRefs=[] when
there is no empirical assertion. Cite only evidence actually needed for factual clauses;
permission IDs are not citations to retain automatically. Never omit support for paper facts.
Use E1/E2 aliases in evidenceRefs/tableBindings, never in published text; Q IDs are not evidence.
Table numbers require exact tableData bindings:
{{"evidenceId":"E1","rowNumber":1,"groupIndex":0,"metric":"FPS","value":"200"}}
This is schema, not evidence: copy actual rowNumber, zero-based groupIndex, metric and value
(key "value", never "exactStringValue"). Name dataset/method/metric; omit unsupported numbers.
Abstract evidence permits only explicit abstract-level wording (detailLevel="abstract").
For existing proposals, choose concrete seed/split/level/budget/confidence settings as YOUR UNEXECUTED PROPOSAL,
not paper-attributed values or promises to preregister later. Correct formulas and label
hypotheses/proposals. Source facts still require evidence; proposed choices need not occur
in the paper. Maintain consistency with accepted definitions and complete required details.'''
    prompt += '\n' + SCIENTIFIC_TERMINOLOGY
    if any(row.get('designContractVersion') == 2 for row in originals.values()):
        from services.deep_research.execution_spec import execution_spec_contract_for_roles
        from services.deep_research.experimental_reasoning import DESIGN_ROLES, design_requirements
        prompt += '\nEvery v2 proposal/suggestion/hypothesis requires one designRole from: ' + json.dumps(sorted(DESIGN_ROLES))
        prompt += ('. For a missing role, assign the appropriate role based on its actual content; '
                  'do not omit the role to bypass checks. Preserve existing valid roles. '
                  'Groups, data and analysis roles require complete executionSpec; versioned budget and '
                  'hypothesis roles require the corresponding complete executionSpec specified below.')
        prompt += '\n' + execution_spec_contract_for_roles({row.get('designRole') for row in originals.values()})
        roles = {row.get('designRole') for row in originals.values()}
        from services.deep_research.design_review_policy import REVIEW_DESIGN_POLICY
        policy = REVIEW_DESIGN_POLICY if any(row.get('protocolContractVersion') == 1 or row.get('workflowContractVersion') in (1, 2)
                                             for row in originals.values()) else None
        # Other roles remain full consistency context and are independently
        # checked. Their writing requirements are not writable in this batch.
        prompt += '\nExperimental deliverables for the active roles (remain consistent with the other definitions):\n' + design_requirements(
            metric_domains, roles=roles if roles <= DESIGN_ROLES.keys() else None, policy=policy)
        prompt += ('\nA structural rejection is not a content approval. Fix substantive omissions in the same revision, '
                   'including concrete intervention levels, per-group budgets and measurement aggregation. '
                   'Choose explicit unexecuted proposal settings when appropriate; do not wait for paper settings '
                   'to define your own diagnostic. Cover all required roles without changing an existing valid role '
                   'or inventing new claim IDs. Do not claim completeness when the available claims cannot cover them. '
                   'Keep all proposed settings consistent across claims and executionSpec.')
    if any(row.get('protocolContractVersion')==1 for row in originals.values()):
        from services.deep_research.experiment_protocol import PROTOCOL_CONTRACT
        prompt += '\n' + PROTOCOL_CONTRACT
    for version in (1, 2):
        if any(row.get('workflowContractVersion') == version for row in originals.values()):
            from services.deep_research.experiment_workflow import workflow_contract
            prompt += '\n' + workflow_contract(version)
    if any(row.get('budgetContractVersion') == 1 for row in originals.values()):
        from services.deep_research.budget_spec import BUDGET_SPEC_CONTRACT
        prompt += '\n' + BUDGET_SPEC_CONTRACT
        prompt += '\nThe budget role owns baseline/recovery settings. Use matching binary group IDs ' \
                  'from the factors order; other roles must remain consistent with this canonical budget.'
    if any(row.get('hypothesisContractVersion') == 1 for row in originals.values()):
        from services.deep_research.hypothesis_spec import HYPOTHESIS_SPEC_CONTRACT
        prompt += '\n' + HYPOTHESIS_SPEC_CONTRACT
        prompt += '\nRepair linked hypothesis/analysis targets jointly, keeping their IDs and exact effect keys. ' \
                  'Select a purpose and compatible method that fulfill the user request, not a weaker substitute.'
    shape = [{'claimId': row['claimId'], 'kind': row['kind'],
              **({'designRole': row['designRole']} if row.get('designRole') else {}),
              'text': '', 'evidenceRefs': [], **({'tableBindings': []} if has_tables else {})}
             for row in originals.values()]
    prompt += ('\nACTIVE OUTPUT TARGETS FOR THIS REQUEST ONLY:\n' + json.dumps(shape, ensure_ascii=False, separators=(',', ':'))
               + '\nFill only these rows, adding required executionSpec fields for their roles. '
               'Fill tableBindings for every retained table measurement; an empty array is only '
               'valid when no table measurements are retained. '
               'Omit a target or return [] if no supported revision is possible. '
               'Do not output any accepted or sibling/context ID, even if it needs improvement. '
               'Each factual clause still requires its own allowed supplied evidenceRefs. '
               'Return only the JSON array; do not rewrite the entire experiment.')
    template = prompt
    def render(selected_rows):
        visible_ids = {row['evidenceId'] for row in selected_rows}
        permissions = {key: [short_ids[ref] for ref in values
                            if ref in short_ids and short_ids[ref] in visible_ids]
                       for key, values in allowed.items()}
        return template.replace(permissions_marker, json.dumps(permissions, ensure_ascii=False, separators=(',', ':')), 1).replace(
            evidence_marker, json.dumps(selected_rows, ensure_ascii=False, separators=(',', ':')), 1)
    if max_prompt_bytes <= 0:
        raise BudgetExhaustedError('repairPromptBytes', max_prompt_bytes, 1)
    # Allocate required full quotes AND context first. Optional candidate
    # passages may not displace a required source's context during fitting.
    required = {ref for claim in originals.values()
                for ref in (claim.get('evidenceRefs', []) if claim.get('text', '').strip() else [])
                if ref in short_ids}
    # Coverage hints are candidates, not citations the original assertion used.
    # Keep them first among optional rows without forcing every broad hint into
    # every batch. Full original citations and their contexts remain mandatory;
    # permissions below remove anything that does not fit the actual request.
    mandatory_rows = [row for row in rows if aliases[row['evidenceId']] in required]
    optional_rows = [row for row in rows if aliases[row['evidenceId']] not in required]
    mandatory_size = len(render(mandatory_rows).encode('utf-8'))
    if mandatory_size > max_prompt_bytes:
        kind = 'repairPromptBytes' if len(render([]).encode('utf-8')) > max_prompt_bytes else 'repairEvidenceBytes'
        raise BudgetExhaustedError(kind, max_prompt_bytes, mandatory_size)
    try:
        prompt, optional_rows = fit_evidence_prompt(optional_rows,
            lambda optional: render([*mandatory_rows, *optional]), max_bytes=max_prompt_bytes)
        rows = [*mandatory_rows, *optional_rows]
    except ValueError as exc:
        if str(exc) != 'prompt_fixed_content_too_large':
            raise
        raise BudgetExhaustedError('repairPromptBytes', max_prompt_bytes,
                                  len(render([]).encode('utf-8'))) from exc
    visible = {aliases[row['evidenceId']] for row in rows}
    allowed = {key: [ref for ref in values if ref in visible] for key, values in allowed.items()}
    return {'prompt': prompt, 'originals': originals, 'aliases': aliases, 'allowed': allowed}


def _parse_repair_response(prepared, response, parse):
    originals, aliases, allowed = (prepared[key] for key in ('originals', 'aliases', 'allowed'))
    finish = getattr(response, 'finish_reason', None) if not isinstance(response, dict) else response.get('finishReason', response.get('finish_reason'))
    if finish == 'length':
        return []
    content = response.content if hasattr(response, 'content') else response.get('content', '')
    revised = parse(content)
    if not isinstance(revised, list):
        return []
    revised = resolve_evidence_aliases({'claims': revised}, aliases)['claims']
    valid, seen = [], set()
    for row in revised:
        if not isinstance(row, dict):
            continue
        key = row.get('claimId')
        original = originals.get(key)
        if not original or key in seen or row.get('kind') != original.get('kind'):
            continue
        seen.add(key)
        new_refs = row.get('evidenceRefs', [])
        if not isinstance(new_refs, list) or any(ref not in allowed.get(key, []) for ref in new_refs):
            continue
        if original.get('designContractVersion') == 2:
            row['designContractVersion'] = 2
        if 'budgetContractVersion' in original:
            row['budgetContractVersion'] = original['budgetContractVersion']
        else:
            row.pop('budgetContractVersion', None)
        if 'hypothesisContractVersion' in original:
            row['hypothesisContractVersion'] = original['hypothesisContractVersion']
        else:
            row.pop('hypothesisContractVersion', None)
        if 'protocolContractVersion' in original:
            row['protocolContractVersion']=original['protocolContractVersion']
        else:
            row.pop('protocolContractVersion',None)
        if 'workflowContractVersion' in original:
            row['workflowContractVersion'] = original['workflowContractVersion']
        else:
            row.pop('workflowContractVersion', None)
        # The repair cannot reassign the claim to another research obligation.
        if 'obligationIds' in original:
            row['obligationIds'] = deepcopy(original['obligationIds'])
        # One observed provider spelling is unambiguous. Normalize syntax only;
        # the exact same identity, numeric and semantic checks still follow.
        if isinstance(row.get('claim'), str):
            if 'text' in row and row['text'] != row['claim']:
                continue
            row['text'] = row.pop('claim')
        if not isinstance(row.get('text'), str) or not row['text'].strip():
            continue
        if original.get('designRole'):
            if row.get('designRole', original['designRole']) != original['designRole']:
                continue
            row['designRole'] = original['designRole']
        from services.deep_research.execution_materialization import materialize_execution_claim
        normalized = normalize_conditions({'claims': [dict(row)]})['claims'][0]
        valid.append(materialize_execution_claim(normalized))
    return valid


def repair_rejected(report, verification, evidence, question, invoke, parse, *,
                    max_prompt_bytes=24000, metric_domains=None, batch_state=None, checkpoint=None,
                    current_budget=None, invoke_request=None):
    """One bounded revision round, split before dispatch when evidence cannot fit.

    At most three requests share full sibling design definitions. Successful
    batch drafts are checkpointed, never promoted without the independent
    verifier. A network/unknown error propagates; it does not create a retry.
    """
    from services.deep_research.contracts import digest, DeepResearchError
    from services.deep_research.repair_batches import split_repair_targets

    targets = {row['claimId'] for row in verification.get('rejected', [])}
    originals = [c for c in report.get('claims', []) if c.get('claimId') in targets]
    if not originals:
        return []
    identity = digest({'report': report, 'verification': verification,
                       'evidence': evidence, 'question': question, 'metricDomains': metric_domains})

    def prepare(ids, results=(), byte_limit=None):
        ids = set(ids)
        prior = {row['claimId']: row for row in results}
        siblings = [prior.get(c['claimId'], c) for c in originals if c['claimId'] not in ids]
        subset = {'accepted': verification.get('accepted', []),
                  'rejected': [row for row in verification.get('rejected', []) if row['claimId'] in ids]}
        return _prepare_repair(report, subset, evidence, question,
            max_prompt_bytes=state['maxPromptBytes'] if byte_limit is None else byte_limit,
            metric_domains=metric_domains, draft_context=siblings)

    state = deepcopy(batch_state) if batch_state is not None else {
        'version': 1, 'inputDigest': identity, 'maxPromptBytes': max_prompt_bytes,
        'batches': [[c['claimId'] for c in originals]], 'results': {}}
    if (type(state.get('version')) is not int or state['version'] != 1 or state.get('inputDigest') != identity
            or type(state.get('maxPromptBytes')) is not int or not 0 <= state['maxPromptBytes'] <= 24000
            or not isinstance(state.get('batches'), list) or not 1 <= len(state['batches']) <= 3
            or any(not isinstance(group, list) or not group
                   or any(not isinstance(cid, str) for cid in group) for group in state['batches'])
            or not isinstance(state.get('results'), dict)):
        raise DeepResearchError('invalid_repair_plan', '保存的修订计划与原始输入不一致，不能重新发送。')
    ids = [cid for group in state['batches'] for cid in group]
    if (len(ids) != len(set(ids)) or set(ids) != {c['claimId'] for c in originals}
            or set(state['results']) != {str(i) for i in range(len(state['results']))}
            or len(state['results']) > len(state['batches'])):
        raise DeepResearchError('invalid_repair_plan', '保存的修订目标无效，不能重新发送。')
    for key, completed in state['results'].items():
        group = state['batches'][int(key)]
        if (not isinstance(completed, list) or any(not isinstance(row, dict)
                or row.get('claimId') not in group for row in completed)
                or len({row['claimId'] for row in completed}) != len(completed)):
            raise DeepResearchError('invalid_repair_plan', '保存的修订草稿身份无效。')
    pending = state.get('pending')
    if pending is not None:
        if (not isinstance(pending, dict) or type(pending.get('index')) is not int
                or pending.get('index') != len(state['results'])
                or pending.get('index') >= len(state['batches'])
                or not isinstance(pending.get('request'), dict)
                or pending.get('digest') != digest(pending['request'])):
            raise DeepResearchError('invalid_repair_plan', '保存的待发送修订请求无效。')
        request = pending['request']
        p = request.get('prepared', {})
        if (not isinstance(p, dict) or not isinstance(p.get('prompt'), str)
                or len(p['prompt'].encode('utf-8')) > state['maxPromptBytes']
                or set(p.get('originals', {})) != set(state['batches'][pending['index']])
                or type(request.get('outputTokens')) is not int or not 1 <= request['outputTokens'] <= 8192):
            raise DeepResearchError('invalid_repair_plan', '保存的待发送修订请求范围无效。')
    if batch_state is None:
        try:
            prepare(state['batches'][0])
        except BudgetExhaustedError as exc:
            if exc.details.get('kind') not in {'repairPromptBytes', 'repairEvidenceBytes'}:
                raise
            state['batches'] = split_repair_targets(originals)
            if len(state['batches']) == 1:
                raise
            # Preflight EVERY batch before spending a model call. An atomic
            # hypothesis/analysis component may not be split to make it fit.
            for group in state['batches']:
                prepare(group)
        if checkpoint:
            checkpoint(deepcopy(state))
    revised = []
    for index, group in enumerate(state['batches']):
        key = str(index)
        if key in state['results']:
            rows = state['results'][key]
        else:
            if state.get('stop'):
                break
            try:
                if 'pending' not in state:
                    from services.deep_research.repair_budget import repair_batch_output_limit, repair_prompt_byte_limit
                    output = repair_batch_output_limit(len(group)) if invoke_request else 8192
                    cap = min(state['maxPromptBytes'], repair_prompt_byte_limit(current_budget(), output)) \
                          if current_budget else state['maxPromptBytes']
                    prepared = prepare(group, revised, cap)
                    request = {'prepared': prepared, 'outputTokens': output}
                    state['pending'] = {'index': index, 'request': request, 'digest': digest(request)}
                    if checkpoint:
                        checkpoint(deepcopy(state))  # Durable exact request BEFORE provider-capable dispatch.
                request = state['pending']['request']
                prepared = request['prepared']
                response = (invoke_request(prepared['prompt'], request['outputTokens'])
                            if invoke_request else invoke(prepared['prompt']))
            except BudgetExhaustedError as exc:
                state['stop'] = {'batch': index, **exc.details}
                if checkpoint:
                    checkpoint(deepcopy(state))
                break  # Keep completed drafts, then independently verify them.
            rows = _parse_repair_response(prepared, response, parse)
            state['results'][key] = rows
            state.pop('pending', None)
            if checkpoint:
                checkpoint(deepcopy(state))
        revised.extend(deepcopy(rows))
    limit = requested_character_limit(question)
    if not limit:
        return revised
    # Preserve independently verifiable repairs that fit, rather than losing
    # every useful revision because a different target exceeds the limit.
    # Omitted targets retain their original rejection/coverage gaps.
    kept, omitted = [], []
    for row in revised:
        candidate = {'claims': [*verification.get('accepted', []), *kept, row]}
        if answer_character_count(candidate) <= limit:
            kept.append(row)
        else:
            omitted.append(row['claimId'])
    if omitted:
        state['omittedForLength'] = omitted
        if checkpoint:
            checkpoint(deepcopy(state))
    return kept
