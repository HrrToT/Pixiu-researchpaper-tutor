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
                    metric_domains=None, draft_context=(), prior_revisions=(),
                    fact_redraft=False, requirement_context=(), source_aware_redraft=False,comparison_reasoning=False,
                    question_priority=False,concise_factual=False,factual_scope=False,declared_table_refs=False,comparison_methodology=False,experimental_intent=False,compact_source_repair=False,shared_experiment_schema=False,experiment_evidence_context=None,experimental_edits=False,experimental_diagnostics=False,experimental_nested_tables=False,experimental_representation=False,experimental_coverage=False,citation_presentation_version=0,configuration_consistency_version=0,repair_evidence_packet_version=0,answer_intents=None,scope_expression=False,table_identity_context=False,claim_check=False,required_scope_ids=(),compact_layout=False,ordinary_advice=False,task_sources=False,request_semantics=False,preserve_answers=False,target_goals=False):
    if type(preserve_answers) is not bool:raise ValueError('Invalid answer preservation policy')
    from services.deep_research.repair_goals import policy_version
    goal_version=policy_version(target_goals)
    if goal_version in (2,3,4) and not (fact_redraft and source_aware_redraft and concise_factual
            and compact_source_repair and factual_redraft_eligible(report)):
        raise ValueError('Point-scoped repair requires compact factual redrafting')
    if not (type(request_semantics) is bool or type(request_semantics) is int and request_semantics==2):raise ValueError('Invalid request semantics policy')
    if type(task_sources) is not bool:raise ValueError('Invalid task source disclosure policy')
    if type(ordinary_advice) is not bool:raise ValueError('Invalid ordinary advice repair policy')
    from services.deep_research.general_advice import repair_eligible
    if ordinary_advice and not repair_eligible(report):raise ValueError('Advice repair cannot rewrite experimental claims')
    if ordinary_advice and not (fact_redraft and source_aware_redraft and concise_factual and compact_source_repair):
        raise ValueError('Advice repair requires source-aware clean redrafting')
    redraft_eligible=factual_redraft_eligible(report) or ordinary_advice
    if type(compact_layout) is not bool:raise ValueError('Invalid factual compact layout policy')
    _validate_scope_ids(required_scope_ids,report,scope_expression)
    if (type(repair_evidence_packet_version) is not int or repair_evidence_packet_version not in (0,1,2,3,4,5)
            or repair_evidence_packet_version in (2,3,4,5) and not experimental_coverage
            or repair_evidence_packet_version in (1,2,3,4,5) and not (experimental_nested_tables and experimental_edits
                and shared_experiment_schema and experimental_intent)):
        raise ValueError('Unsupported experimental repair input contract')
    if type(configuration_consistency_version) is not int or configuration_consistency_version not in (0,2):
        raise ValueError('Unsupported configuration consistency contract')
    if type(citation_presentation_version) is not int or citation_presentation_version not in (0,2,3,4):
        raise ValueError('Unsupported citation presentation contract')
    rejected = {row['claimId']: row for row in verification.get('rejected', [])}
    originals = {row['claimId']: row for row in report.get('claims', []) if row.get('claimId') in rejected}
    if not originals:
        return []
    if repair_evidence_packet_version in (1,2,3,4,5) and any(c.get('kind') not in {'proposal','suggestion','hypothesis'}
            for c in originals.values()):raise ValueError('Experimental repair input requires prospective targets')
    if experimental_diagnostics and (not experimental_edits or not experimental_intent):
        raise ValueError('Experimental diagnostics require prospective field edits')
    if experimental_nested_tables and not experimental_diagnostics:
        raise ValueError('Nested experimental tables require diagnostic field edits')
    if experimental_representation and not experimental_nested_tables:
        raise ValueError('Experimental representation requires nested field edits')
    if experimental_coverage and not experimental_representation:
        raise ValueError('Experimental coverage requires representation-aware edits')
    if experimental_edits:
        from services.deep_research.experiment_edits import can_edit
        if not shared_experiment_schema or not can_edit(report):
            raise ValueError('Experimental edits require existing compatible complete role objects')
    hinted = {ref for row in rejected.values() for ref in row.get('missingEvidenceRefs', [])
              if isinstance(ref, str)}
    evidence = sorted(evidence, key=lambda e: e.get('evidenceId') not in hinted)
    allowed = repair_evidence_scope(list(originals.values()), evidence,
        **({'question':question} if question_priority else {}))
    if experiment_evidence_context is not None:
        from services.deep_research.experiment_evidence import expand
        allowed=expand(list(originals.values()),evidence,allowed,experiment_evidence_context)
    refs = {ref for values in allowed.values() for ref in values}
    selected = [e for e in evidence if e['evidenceId'] in refs]
    if question_priority:
        from services.deep_research.evidence_priority import prioritize_existing_evidence
        selected=prioritize_existing_evidence(selected,question)
    if experiment_evidence_context is not None:
        from services.deep_research.synthesis_evidence import order_premises
        related={oid for c in originals.values() for oid in c.get('obligationIds',[])}
        selected,_=order_premises(selected,[{'obligations':[o for o in experiment_evidence_context['requirements']
            if o['obligationId'] in related]}],limit=len(selected),membership_intents=True)
    aliases = {f'E{i + 1}': e['evidenceId'] for i, e in enumerate(selected)}
    short_ids = {full: short for short, full in aliases.items()}
    original_refs = {ref for row in originals.values() for ref in row.get('evidenceRefs', [])}
    rows = [
        {key: value for key, value in {
         'evidenceId': short_ids[e['evidenceId']], 'quote': e.get('quote', ''),
         'sourceContext': surrounding_context(e), 'location': e.get('location', {}),
         'accessLevel': e.get('accessLevel'), 'conditions': e.get('conditions', {}),
         'publicationIdentity': e.get('sourcePublicationIdentity'),
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
                if key not in {'designContractVersion', 'budgetContractVersion', 'hypothesisContractVersion','protocolContractVersion','workflowContractVersion','draftingBasis'}
                and not (key in {'conditions', 'obligationIds'} and value in ({}, []))}
    input_claims = [compact_claim_view(row) for row in input_claims]
    redraft_instruction = ''
    source_instruction = ''
    if any(row.get('publicationIdentity') for row in rows):
        from services.deep_research.publication_identity import GUIDANCE as publication_guidance
        source_instruction = '\n' + publication_guidance
    if experiment_evidence_context is not None:
        from services.deep_research.factual_source_context import factual_source_context
        source_catalog={s['sourceId']:s for s in experiment_evidence_context['sources']}
        def source_metadata(item):
            source=source_catalog.get(item.get('sourceId'),{})
            return ({**item,'ownerMaterialId':source['ownerMaterialId']} if source and all(
                item.get(key)==source[field] for key,field in (('sourceWorkId','workId'),
                ('sourceVersionId','versionId'),('contentHash','contentHash'))) else item)
        source_context,evidence_sources=factual_source_context([source_metadata(item) for item in selected],
            experiment_evidence_context['requirements'],related)
        from services.deep_research.experiment_evidence import factor_registry
        source_instruction='\nOriginal source registry (metadata only, not support or citations):\n'+json.dumps(
            factor_registry(source_context),ensure_ascii=False,separators=(',',':'))+(
            '\nEach requirement group applies its requiredSources mapping to every listed obligationId. '
            'P IDs identify exact work/version/access/ownership. publicationIdentity pins the publication revision, '
            'not a scientific fact. Each factual clause still needs its OWN supplied E quotations.\n')
        by_id={item['evidenceId']:item for item in selected}
        for row in rows:
            row['sourceRef']=evidence_sources[aliases[row['evidenceId']]]
            row['contentHash']=by_id[aliases[row['evidenceId']]]['contentHash']
        from services.deep_research.factual_repair import compact_rows
        rows=compact_rows(rows,source_context)
    if fact_redraft and redraft_eligible:
        # Omit rejected wording from the generation view, not audit storage.
        # Keep original citations mandatory below and full originals in the
        # prepared record for parsing, scope and unchanged-rejection checks.
        if type(claim_check) is int and claim_check==9:
            input_claims=[{key:value for key,value in row.items() if key in {'claimId','kind','obligationIds'}}
                          for row in input_claims]
        else:
            input_claims = [{key:value for key,value in row.items() if key not in {'text','conditions'}}
                            for row in input_claims]
        related = {oid for row in originals.values() for oid in row.get('obligationIds', [])}
        active_requirements = [{key:row[key] for key in ('obligationId','question','completionCriteria') if key in row}
                               for row in requirement_context if not related or row.get('obligationId') in related]
        if source_aware_redraft:
            from services.deep_research.factual_source_context import factual_source_context
            context,evidence_sources=factual_source_context(selected,requirement_context,related)
            by_evidence={item['evidenceId']:item for item in selected}
            for row in rows:
                full_id=aliases[row['evidenceId']]
                row['sourceRef']=evidence_sources[full_id]
                row['contentHash']=by_evidence[full_id]['contentHash']
            source_instruction+=('\nFrozen factual source requirements and identities (metadata, NOT paper evidence):\n'
                +json.dumps(context,ensure_ascii=False,separators=(',',':'))
                +'\nP IDs label source metadata, never citations or published words. Required source IDs map to '
                'available P IDs; an empty list means that source is unavailable in this request. '
                'Use the corresponding E quotations to satisfy EACH designated source requirement. '
                'A generic explanation citing one work does not establish another work-specific premise. '
                'Combine actual supplied premises when the question requires reasoning, without inventing '
                'a measurement or claiming the author explicitly stated your inference. Do not keep '
                'irrelevant citations to meet a count: leave the unsupported source-specific part open.\n')
        redraft_instruction = ('Source-grounded factual redraft: rejected prose/conditions are omitted from '
            'the generation view; they remain in the audit record. Rebuild these exact IDs from their '
            'allowed quotations and the requested points below. Do not guess missing premises. '
            'For explanations prefer qualitative roles and causal steps; omit unrequested parameter counts '
            'and implementation details. Correct EVERY check, including additionalChecks. '
            'Accepted points above must not be repeated. These requirements specify questions, not facts:\n'
            + json.dumps(active_requirements,ensure_ascii=False,separators=(',',':')) + '\n')
    from services.deep_research.repair_prompt import factor_repair_questions, factor_design_deliverables
    question_dictionary, packed_checks = factor_repair_questions(rejected)
    if any(row.get('designContractVersion') == 2 for row in originals.values()):
        from services.deep_research.experimental_reasoning import DESIGN_ROLES
        packed_checks = factor_design_deliverables(packed_checks, originals.values(), DESIGN_ROLES)
    for check in packed_checks.values():
        if isinstance(check.get('missingEvidenceRefs'), list):
            check['missingEvidenceRefs'] = [short_ids.get(ref, ref) if isinstance(ref, str) else ref
                                            for ref in check['missingEvidenceRefs']]
        if declared_table_refs:
            for item in [check,*(check.get('additionalChecks') or [])]:
                if not isinstance(item,dict):
                    continue
                references=item.get('availableTableReferences')
                for ref in references if isinstance(references,list) else []:
                    if isinstance(ref,dict) and isinstance(ref.get('evidenceId'),str):
                        ref['evidenceId']=short_ids.get(ref['evidenceId'],ref['evidenceId'])
    revision_shape = {'claimId': 'original ID', 'kind': 'original kind', 'text': 'revised wording',
                      'evidenceRefs': ['E1'], 'conditions': {}, 'detailLevel': 'fulltext'}
    if goal_version==4:
        revision_shape['discardedDraftSpans']=['exact unsupported phrase removed from original draft; [] if none']
    if scope_expression: revision_shape['scopeExpression'] = None
    if factual_scope in (2,3,4) and fact_redraft and redraft_eligible:
        from services.deep_research.factual_scope import DRAFTING_SCHEMA
        revision_shape={'draftingBasis':DRAFTING_SCHEMA,**revision_shape}
    has_tables = any(row.get('tableData') for row in rows) or any(
        row.get('tableBindings') for row in originals.values())
    if has_tables:
        revision_shape['tableBindings'] = [{'evidenceId': 'E1', 'rowNumber': 'actual integer',
            'groupIndex': 'actual zero-based integer', 'metric':
                'exact member of tableData.groups[groupIndex][1]' if type(declared_table_refs) is int and declared_table_refs==4 else 'exact header',
            'value': 'exact string'}]
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
    character_limit = requested_character_limit(question)
    accepted_characters = answer_character_count({'claims': verification.get('accepted', [])})
    # Revisions from earlier batches remain unverified, but still occupy the
    # proposed answer's length allowance. They are not silently rewritten here.
    prior_characters = answer_character_count({'claims': prior_revisions})
    length_contract = ''
    if character_limit:
        remaining = max(0, character_limit - accepted_characters - prior_characters)
        length_contract = (f'\nAnswer character allowance: total={character_limit}; '
                           f'immutable accepted={accepted_characters}; earlier batch drafts={prior_characters}; '
                           f'ALL current target text plus conditions together must fit remaining={remaining}.\n'
                           'Accepted answer content (already answered; do not repeat it):\n'
                           + json.dumps([{key: row[key] for key in ('claimId', 'text', 'conditions') if key in row}
                                         for row in verification.get('accepted', [])],
                                        ensure_ascii=False, separators=(',', ':'))
                           + '\nFill only the missing part. Do not repeat an accepted mechanism in a motivation repair.\n')
    from services.deep_research.verification_context import CONFIG_ROLES, configuration_context
    if (all(row.get('designRole') in CONFIG_ROLES for row in originals.values())
            and any(row.get('protocolContractVersion') in (1, 2) or row.get('workflowContractVersion') in (1, 2, 3, 4)
                    for row in originals.values())):
        # Versioned operational repairs need all operational definitions and
        # explicit dependencies, not unrelated scientific prose. Keep accepted
        # versus unverified sibling status separate, and never change storage.
        selected_context = configuration_context(list(originals.values()), [*proposal_context, *sibling_context])
        retained = {row['claimId'] for row in selected_context}
        proposal_context = [row for row in proposal_context if row['claimId'] in retained]
        sibling_context = [row for row in sibling_context if row['claimId'] in retained]
    table_instructions = '''Table numbers require exact tableData bindings:
{"evidenceId":"E1","rowNumber":1,"groupIndex":0,"metric":"FPS","value":"200"}
This is schema, not evidence: copy actual rowNumber, zero-based groupIndex, metric and value
(key "value", never "exactStringValue"). Name dataset/method/metric; omit unsupported numbers.
Bind only numerical values stated in the revised text. Do not copy a whole table row
or add new measurements to repair a missing label. Preserve the user's requested
conditions/limitations before adding secondary examples. Method bibliography numbers
may be omitted, but stars, ablation and training variants must stay distinguishable.
''' if has_tables else ''
    prompt = f'''Revise only the targets; narrow unsupported wording or omit it.
answer_incomplete requires filling requested omissions, conditioning inputs and applicability,
not merely shortening. A missing mechanism explanation needs how/why the requested
input affects the operation/output, in ordinary words if requested for novices;
lead with the actual change and its consequence, not a derivative or method label.
For novices define essential unfamiliar concepts through concrete actions; connect
the observed error/signal to the adjustment and later consequence without assuming
optimization/derivative knowledge. Do not invent supervision or a guaranteed update.
listing names or repeating a technical operation is not sufficient. Do not add
unsupported mechanics: use the allowed evidence or retain the limitation.
Equation/parameter-link deductions may be inference claims with explicit cited
premises and conditional effects; they do not establish guaranteed convergence.
If a central inference is supported but an appended list of mechanisms is not,
retain only the supported conclusion and premises. Do not replace unsupported
details with a paper-wide claim that those details were never measured.
absence_not_established requires bounded positive evidence:
missing passages do not prove paper-wide absence; finite results do not prove universality.
Replace a rejected absence assertion with the limits of the ACTUALLY CITED evidence,
for example "当前取得的证据支持…，不足以证明…在其他条件仍成立". Fill only supported
scope; never retain "论文未验证/未提供…" without explicit evidence of that absence.
uncited_device_condition means the hardware name occurs outside this claim's citations:
cite its actual supporting allowed passage in this claim or remove/narrow that condition.
Check ALL factual conditions, not only main text. Preserve exact baseline variants and
do not transfer a retrained baseline's platform onto another row. This is not permission
to invent a hardware source or to borrow another claim's uncited evidence.
numeric_mismatch in a reported claim requires using original cited values only:
remove computed differences/ratios/percentages that the paper did not report.
Keep the operands and qualitative comparison when supported; do not append your
own calculation while preserving kind="reported". Each table group name must copy
its exact tableData label, even if another passage uses a different spelling.
Question: {question}
{length_contract}
Accepted experimental definitions (consistency only; do not revise these or treat them as paper evidence):
{json.dumps(proposal_context, ensure_ascii=False, separators=(',', ':'))}
Other draft definitions (UNVERIFIED consistency context, not frozen choices or paper evidence;
these may be revised in other batches; never return a verdict or revision for these IDs):
{json.dumps(sibling_context, ensure_ascii=False, separators=(',', ':'))}
App suffixes are omitted; complete executionSpec remains and is rendered. Keep prose consistent; do not duplicate it.
Missing-question dictionary (missingQuestionIds refer here; Q IDs are internal, never evidence/published text):
{json.dumps(question_dictionary, ensure_ascii=False, separators=(',', ':'))}
{redraft_instruction}detailRequirementRole points to the identical required role definition under Experimental deliverables below.
Rejected claims and checks:
{json.dumps([{'claim': row, 'check': packed_checks[row['claimId']]} for row in input_claims], ensure_ascii=False, separators=(',', ':'))}
Allowed evidence IDs per claim (candidate permissions, not proof of support):
{permissions_marker}
Exact available evidence:
{evidence_marker}
missingEvidenceRefs are candidates; use only each claim's allowed evidence actually listed above.
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
{table_instructions}
Abstract evidence permits only explicit abstract-level wording (detailLevel="abstract").
For existing proposals, choose concrete seed/split/level/budget/confidence settings as YOUR UNEXECUTED PROPOSAL,
not paper-attributed values or promises to preregister later. Correct formulas and label
hypotheses/proposals. Source facts still require evidence; proposed choices need not occur
in the paper. Maintain consistency with accepted definitions and complete required details.'''
    prospective = not ordinary_advice and experimental_intent and all(row.get('kind') in {'proposal','suggestion','hypothesis'} for row in originals.values())
    if prospective:
        from services.deep_research.experiment_intent import repair_prompt as experiment_repair_prompt
        prompt = experiment_repair_prompt(question=question,length_contract=length_contract,
            accepted=proposal_context,siblings=sibling_context,questions=question_dictionary,targets=input_claims,
            checks=packed_checks,permissions_marker=permissions_marker,evidence_marker=evidence_marker,
            shape=revision_shape,table_instructions=table_instructions,
            policy_version=experimental_intent if type(experimental_intent) is int and experimental_intent in (2,3) else 1)
    prompt += '\n' + SCIENTIFIC_TERMINOLOGY
    if source_instruction:
        prompt += source_instruction
    if comparison_reasoning and all(row.get('kind') in {'reported','inference'} for row in originals.values()):
        from services.deep_research.comparison_reasoning import GUIDANCE
        prompt+='\n'+GUIDANCE
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
        policy = REVIEW_DESIGN_POLICY if any(row.get('protocolContractVersion') in (1, 2) or row.get('workflowContractVersion') in (1, 2, 3, 4)
                                             for row in originals.values()) else None
        # Other roles remain full consistency context and are independently
        # checked. Their writing requirements are not writable in this batch.
        if (roles <= CONFIG_ROLES and policy) or any(
                row.get('protocolContractVersion') == 2 or row.get('workflowContractVersion') == 4
                for row in report.get('claims', [])):
            # Generation needs operational drafting guidance; the independent
            # reviewer still applies the complete scientific policy afterwards.
            from services.deep_research.design_drafting import design_drafting_requirements
            groups=[row.get('executionSpec',{}).get('factors') for row in report.get('claims',[])
                    if row.get('designRole')=='groups' and isinstance(row.get('executionSpec'),dict)]
            single_factor=bool(groups) and all(isinstance(factors,list) and len(factors)==1 for factors in groups)
            requirements = design_drafting_requirements(metric_domains, compact=True, roles=roles,
                **({'targeted':True,'factorial_reference':not single_factor} if prospective else {}))
        else:
            requirements = design_requirements(metric_domains,
                roles=roles if roles <= DESIGN_ROLES.keys() else None, policy=policy)
        prompt += '\nExperimental deliverables for the active roles (remain consistent with the other definitions):\n' + requirements
        prompt += ('\nA structural rejection is not a content approval. Fix substantive omissions in the same revision, '
                   'including concrete intervention levels, per-group budgets and measurement aggregation. '
                   'Choose explicit unexecuted proposal settings when appropriate; do not wait for paper settings '
                   'to define your own diagnostic. Cover all required roles without changing an existing valid role '
                   'or inventing new claim IDs. Do not claim completeness when the available claims cannot cover them. '
                   'Keep all proposed settings consistent across claims and executionSpec.')
    for version in (1, 2):
        if any(row.get('protocolContractVersion')==version for row in originals.values()):
            from services.deep_research.experiment_protocol import protocol_contract
            prompt += '\n' + protocol_contract(version)
    for version in (1, 2, 3, 4):
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
    shape = [{**({'draftingBasis':DRAFTING_SCHEMA} if factual_scope in (2,3,4) and fact_redraft and redraft_eligible else {}),
              'claimId': row['claimId'], 'kind': row['kind'],
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
    if scope_expression:
        for target in shape: target['scopeExpression'] = None
    compact_factual=concise_factual and fact_redraft and redraft_eligible
    if compact_factual:
        from services.deep_research.factual_redraft_prompt import render as factual_prompt
        prompt=factual_prompt(question=question,length_contract=length_contract,requirements=active_requirements,
            source_instruction=source_instruction,targets=input_claims,checks=packed_checks,questions=question_dictionary,
            permissions_marker=permissions_marker,evidence_marker=evidence_marker,shape=shape,
            table_instructions=table_instructions,terminology=SCIENTIFIC_TERMINOLOGY)
        if factual_scope:
            from services.deep_research.factual_scope import DRAFT_GUIDANCE
            prompt+='\n'+DRAFT_GUIDANCE
    if declared_table_refs and not (type(declared_table_refs) is int and declared_table_refs==4):
        from services.deep_research.table_bindings import reference_guidance
        prompt+='\n'+reference_guidance(declared_table_refs)
    if comparison_methodology and not prospective:
        from services.deep_research.comparison_methodology import REFERENCE
        prompt+='\n'+REFERENCE
    if compact_source_repair and compact_factual and source_aware_redraft:
        from services.deep_research.factual_repair import render as compact_repair_prompt, compact_rows
        from services.deep_research.repair_goals import point_hints
        rows=compact_rows(rows,context)
        prompt=compact_repair_prompt(question=question,length_contract=length_contract,
            requirements=active_requirements,source_context=context,targets=input_claims,
            checks=packed_checks,questions=question_dictionary,permissions_marker=permissions_marker,
            evidence_marker=evidence_marker,schema=revision_shape,
            **({'target_goals':target_goals} if target_goals else {}),
            **({'target_hints':point_hints(originals.values())} if goal_version in (2,3,4) else {}))
    if shared_experiment_schema and prospective:
        from services.deep_research.experiment_repair import compatible,render as experiment_prompt
        feedback_options = {}
        if experimental_edits:
            from services.deep_research.experiment_edit_prompt import render as experiment_prompt
        if experimental_diagnostics:
            from services.deep_research.experiment_feedback_prompt import render as experiment_prompt
            from services.deep_research.experiment_diagnostics import feedback
            feedback_options['diagnostics'] = feedback(list(originals.values()), [
                c for c in report.get('claims', []) if c.get('claimId') not in originals])
        if experimental_nested_tables:
            from services.deep_research.experiment_nested_prompt import render as experiment_prompt
            if configuration_consistency_version==2:feedback_options['configuration_consistency_version']=2
        if experimental_representation:
            feedback_options['parameter_rows']=True
        if repair_evidence_packet_version in (1,2,3,4,5):
            from services.deep_research.experiment_repair_input import render as experiment_prompt
            if repair_evidence_packet_version in (2,3,4,5):
                from services.deep_research.experiment_repair_input_brief import render as experiment_prompt
            if repair_evidence_packet_version in (3,4,5):
                from services.deep_research.experiment_repair_input_grammar import render as experiment_prompt
            if repair_evidence_packet_version in (4,5):
                from services.deep_research.repair_check_text import render as experiment_prompt
            if repair_evidence_packet_version==5:
                from services.deep_research.repair_bound_values import render as experiment_prompt
        if compatible(report):
            prompt=experiment_prompt(question=question,length_contract=length_contract,
                accepted=proposal_context,siblings=sibling_context,questions=question_dictionary,
                targets=input_claims,checks=packed_checks,permissions_marker=permissions_marker,
                evidence_marker=evidence_marker,shape=revision_shape,table_instructions=table_instructions,
                source_instruction=source_instruction,metric_domains=metric_domains,
                policy_version=experimental_intent,declared_table_refs=declared_table_refs,
                terminology=SCIENTIFIC_TERMINOLOGY,concise_policy=experiment_evidence_context is not None,**feedback_options)
    # Schema renderers above can replace the entire prompt. Keep the current
    # packet-key contract after the final renderer, inside the byte fitter.
    if type(declared_table_refs) is int and declared_table_refs==4 and not (goal_version in (2,3,4) and not has_tables):
        from services.deep_research.table_bindings import reference_guidance
        prompt+='\n'+reference_guidance(4)
    if preserve_answers:
        from services.deep_research.answer_preservation import GUIDANCE
        prompt+='\n'+GUIDANCE
    if request_semantics:
        from services.deep_research.request_semantics import DRAFT_GUIDANCE
        prompt+='\n'+DRAFT_GUIDANCE+'\nRepair preserves original kind: if an original reported target cannot be supported as an author fact, leave it unresolved rather than inventing an author recommendation or changing kind.'
    if task_sources:
        from services.deep_research.access_disclosure import GUIDANCE as access_guidance
        prompt+='\n'+access_guidance
    if ordinary_advice:
        from services.deep_research.general_advice import REPAIR_GUIDANCE
        prompt=prompt.replace('Rebuild ONLY these rejected factual answer targets',
            'Rebuild ONLY these rejected answer targets (paper facts and ordinary recommendations)')
        prompt+='\n'+REPAIR_GUIDANCE
    if compact_layout:
        from services.deep_research.short_factual_layout import GUIDANCE
        prompt+='\n'+GUIDANCE
    if experimental_coverage:
        from services.deep_research.repair_coverage import add_contract
        prompt=add_contract(prompt,originals,**({'version':3 if repair_evidence_packet_version in (2,3,4,5) else 2}
            if repair_evidence_packet_version in (1,2,3,4,5) else {}))
    if scope_expression:
        from services.deep_research.scope_expression import guidance as scope_guidance
        prompt += '\n' + scope_guidance(scope_expression if type(scope_expression) is int and scope_expression in (2,3,4) else 1)
    if answer_intents is not None:
        from services.deep_research.answer_point_intent import repair_guidance
        prompt += repair_guidance(answer_intents, originals,**({'clarify_shared_sources':True} if type(claim_check) is int and claim_check in (8,9) else {}))
    if table_identity_context and not (goal_version in (2,3,4) and not has_tables):
        from services.deep_research.table_identity_context import guidance as table_identity_guidance
        prompt += '\n'+table_identity_guidance(2 if type(table_identity_context) is int and table_identity_context==2 else 1)
    if claim_check:
        from services.deep_research.claim_check import GUIDANCE as CLAIM_CHECK_GUIDANCE, ASSESSMENT_GUIDANCE
        prompt += '\n'+(ASSESSMENT_GUIDANCE if type(claim_check) is int and claim_check in (4,5,6,7,8,9) else CLAIM_CHECK_GUIDANCE)
    if type(claim_check) is int and claim_check==9 and fact_redraft and redraft_eligible:
        prompt+='''\nOld citations, cell bindings, access labels and verification tags are hidden draft choices, not frozen
requirements. Rebuild them from THIS target's allowed original quotations. Bind only
measurements retained in the revised text; choose a minimal informative observation.
The original quotations/context remain supplied and no new permission is granted.
Do not infer missing paper experiments from omitted/nonselected passages.
scopeExpression values become published text: write explanations in Chinese, keeping
original dataset/method/metric names. 重写先给有条件的判断，再给最小依据；引用重新选择。
'''
    from services.deep_research.claim_check import inference_repair_ids
    inference_ids=inference_repair_ids(report,verification,claim_check)
    if inference_ids:
        prompt=prompt.replace('same claimId/kind','same claimId; keep kind except the permitted transition below')
        prompt+='\nReported-to-inference edit IDs: '+json.dumps(inference_ids,ensure_ascii=False)+'''
For these IDs only, when filling answer_incomplete with YOUR evidence-grounded
judgement, you may change kind from reported to inference. Keep claimId, source
permissions and obligations. Change the actual wording, not just the kind tag.
Declare draftingBasis.scopeDecision="bounded_inference"; this is unverified intent.
Other kinds/targets stay unchanged. Keep exact cited input cells for any derived
comparison; no new factual premise is authorized. The revised inference is checked
independently; this permission does not establish evidence support.
'''
    inference_reasons={}
    if type(claim_check) is int and claim_check in (8,9) and inference_ids:
        prompt=prompt.replace('when filling answer_incomplete with YOUR evidence-grounded',
            'when correcting answer_incomplete or semantic_unresolved with YOUR evidence-grounded')
        for key in inference_ids:
            check=rejected[key];extra=check.get('additionalChecks')
            checks=[check,*[c for c in extra if isinstance(c,dict)]] if isinstance(extra,list) else [check]
            inference_reasons[key]='answer_incomplete' if any(c.get('reason')=='answer_incomplete' for c in checks) else 'semantic_unresolved'
    if required_scope_ids:
        prompt+='\nRequired scope-role claim IDs: '+json.dumps(list(required_scope_ids),ensure_ascii=False)+'''
Each listed target must return a non-null scopeExpression, text="" and conditions={}.
Revise its authored fields using permitted evidence; never downgrade it to free prose.
If a supported revision is not possible, omit that target rather than bypass scope review.
'''
    if goal_version==4:
        from services.deep_research.repair_removals import GUIDANCE as REMOVAL_GUIDANCE
        prompt+='\n'+REMOVAL_GUIDANCE
    condition_marker=None
    if type(claim_check) is int and claim_check in (7,8,9):
        from services.deep_research.condition_source_index import GUIDANCE as CONDITION_GUIDANCE
        condition_marker='__CONDITION_SOURCES_'+uuid4().hex+'__'
        prompt+='\n'+CONDITION_GUIDANCE+'\nCondition source index (navigation only):\n'+condition_marker
    note_navigation=type(table_identity_context) is int and table_identity_context==2 and factual_redraft_eligible(report) and not (goal_version in (2,3,4) and not has_tables)
    template = prompt
    from services.deep_research.experiment_edits import columnar
    def render(selected_rows):
        visible_ids = {row['evidenceId'] for row in selected_rows}
        permissions = {key: [short_ids[ref] for ref in values
                            if ref in short_ids and short_ids[ref] in visible_ids]
                       for key, values in allowed.items()}
        wire=columnar(selected_rows) if experimental_edits else selected_rows
        legend=''
        if repair_evidence_packet_version in (1,2,3,4,5):
            from services.deep_research.repair_evidence_packet import encode
            wire,legend=encode(selected_rows)
        result=template.replace(permissions_marker, json.dumps(permissions, ensure_ascii=False, separators=(',', ':')), 1).replace(
            evidence_marker,json.dumps(wire,ensure_ascii=False,separators=(',',':'))+('\n'+legend if legend else ''),1)
        if condition_marker:
            from services.deep_research.condition_source_index import build as condition_index
            literal_ids={short_ids[e['evidenceId']] for e in selected if e.get('verification',{}).get('literal')=='passed'}
            result=result.replace(condition_marker,json.dumps(condition_index(selected_rows,permissions,literal_ids=literal_ids),ensure_ascii=False,separators=(',',':')),1)
        if note_navigation:
            from services.deep_research.table_note_index import build as note_index
            owners={short_ids[e['evidenceId']]:(e.get('sourceWorkId'),e.get('sourceVersionId')) for e in selected}
            literal_ids={short_ids[e['evidenceId']] for e in selected if e.get('verification',{}).get('literal')=='passed'}
            result+='\nTable-note candidates (unverified navigation):\n'+json.dumps(note_index(selected_rows,owners,literal_ids=literal_ids,permissions=permissions),ensure_ascii=False,separators=(',',':'))
        return result
    if max_prompt_bytes <= 0:
        raise BudgetExhaustedError('repairPromptBytes', max_prompt_bytes, 1)
    # Allocate required full quotes AND context first. Optional candidate
    # passages may not displace a required source's context during fitting.
    required = {ref for claim in originals.values()
                for ref in (claim.get('evidenceRefs', []) if claim.get('text', '').strip() or
                    goal_version in (2,3,4) and isinstance(claim.get('scopeExpression'),dict) and claim['scopeExpression'] else [])
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
    return {**({'compactLayoutVersion':1} if compact_layout else {}),'prompt': prompt, 'originals': originals, 'aliases': aliases, 'allowed': allowed,
            **({'repairRemovalContractVersion':1} if goal_version==4 else {}),
            **({'requiredScopeIds':list(required_scope_ids)} if required_scope_ids else {}),
            **({'reportedInferenceRepairIds':inference_ids} if inference_ids else {}),
            **({'reportedInferenceRepairReasons':inference_reasons} if inference_reasons else {}),
            **({'scopeExpressionContractVersion':scope_expression if type(scope_expression) is int and scope_expression in (2,3,4) else 1} if scope_expression else {}),
            **({'repairEvidencePacketVersion':repair_evidence_packet_version} if repair_evidence_packet_version in (1,2,3,4,5) else {}),
            **({'editFormatVersion':1} if experimental_edits else {}),
            **({'diagnosticVersion':1,'schemaFeedback':feedback_options['diagnostics']} if experimental_diagnostics else {}),
            **({'nestedTablesVersion':1} if experimental_nested_tables else {}),
            **({'representationContractVersion':1} if experimental_representation else {}),
            **({'coverageContractVersion':1} if experimental_coverage else {}),
            **({'presentationVersion':citation_presentation_version if citation_presentation_version in (2,3,4) else 1,'presentationQuotes':{row['evidenceId']:row.get('quote','')+'\n'+
                json.dumps(row.get('sourceContext',{}),ensure_ascii=False) for row in rows}} if compact_factual or citation_presentation_version in (2,3,4) else {})}


def _parse_repair_response(prepared, response, parse, presentation_audit=None,drafting_audit=None, *, strict_response=False,representation_audit=None,coverage_audit=None,scope_audit=None):
    originals, aliases, allowed = (prepared[key] for key in ('originals', 'aliases', 'allowed'))
    finish = getattr(response, 'finish_reason', None) if not isinstance(response, dict) else response.get('finishReason', response.get('finish_reason'))
    if finish == 'length':
        if type(prepared.get('coverageContractVersion')) is int and prepared['coverageContractVersion']==1 and coverage_audit is not None:
            from services.deep_research.repair_coverage import partition
            _,audit=partition(originals,[]);audit.update(responseState='received_truncated',expandedRevisionIds=[])
            coverage_audit.append(audit)
        return []
    content = response.content if hasattr(response, 'content') else response.get('content', '')
    try:
        revised = parse(content)
    except (ValueError, TypeError) as exc:
        if not strict_response:
            raise
        from services.deep_research.contracts import DeepResearchError
        raise DeepResearchError('invalid_repair_response', '修订结果未能解析；已保留此前核实的内容。',
                                {'responseState': 'received_invalid'}) from exc
    if not isinstance(revised, list):
        if strict_response:
            from services.deep_research.contracts import DeepResearchError
            raise DeepResearchError('invalid_repair_response', '修订结果未能解析；已保留此前核实的内容。',
                                    {'responseState': 'received_invalid'})
        return []
    coverage=None
    if type(prepared.get('coverageContractVersion')) is int and prepared['coverageContractVersion']==1:
        from services.deep_research.repair_coverage import partition
        revised,coverage=partition(originals,revised)
    if type(prepared.get('editFormatVersion')) is int and prepared['editFormatVersion']==1:
        from services.deep_research.experiment_edits import expand
        revised=expand(prepared,revised,representation_audit)
    revised = resolve_evidence_aliases({'claims': revised}, aliases)['claims']
    valid, seen = [], set()
    for row in revised:
        if not isinstance(row, dict):
            continue
        if prepared.get('compactLayoutVersion')==1:
            from services.deep_research.short_factual_layout import valid_access_labels
            if not valid_access_labels([row]):continue
        key = row.get('claimId')
        original = originals.get(key)
        if not original or key in seen:
            continue
        transition=(key in prepared.get('reportedInferenceRepairIds',[]) and original.get('kind')=='reported'
            and row.get('kind')=='inference' and isinstance(row.get('draftingBasis'),dict)
            and row['draftingBasis'].get('scopeDecision')=='bounded_inference'
            and isinstance(row.get('text'),str) and bool(row['text'].strip())
            and ' '.join(row['text'].split())!=' '.join(original.get('text','').split()))
        if row.get('kind')!=original.get('kind') and not transition:
            continue
        removals=None
        if prepared.get('repairRemovalContractVersion')==1:
            from services.deep_research.repair_removals import checked_spans
            try:removals=checked_spans(row,original)
            except ValueError:continue
            row.pop('discardedDraftSpans')
        seen.add(key)
        new_refs = row.get('evidenceRefs', [])
        if not isinstance(new_refs, list) or any(ref not in allowed.get(key, []) for ref in new_refs):
            continue
        if key in prepared.get('requiredScopeIds',[]) and not isinstance(row.get('scopeExpression'),dict):
            if scope_audit is not None:scope_audit.append({'claimId':key,'error':'scope_role_downgrade'})
            continue
        if type(prepared.get('scopeExpressionContractVersion')) is int and prepared['scopeExpressionContractVersion'] in (1,2,3,4):
            from services.deep_research.scope_expression import materialize as materialize_scope
            try: row, audit = materialize_scope(row, prepared['scopeExpressionContractVersion'])
            except ValueError:
                if scope_audit is not None: scope_audit.append({'claimId':key,'error':'invalid_scope_expression'})
                continue
            if audit and scope_audit is not None: scope_audit.append(audit)
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
        if drafting_audit is not None and 'draftingBasis' in row:
            drafting_audit.append({'claimId':key,'basis':row.pop('draftingBasis'),
                **({'discardedDraftSpans':removals,'removalVerification':'edit_consistency_only'} if removals is not None else {}),
                **({'kindTransition':{'from':'reported','to':'inference','reason':prepared.get('reportedInferenceRepairReasons',{}).get(key,'answer_incomplete'),'verification':'unchecked'}} if transition else {})})
        if original.get('designRole'):
            if row.get('designRole', original['designRole']) != original['designRole']:
                continue
            row['designRole'] = original['designRole']
        from services.deep_research.execution_materialization import materialize_execution_claim
        normalized = normalize_conditions({'claims': [dict(row)]})['claims'][0]
        if type(prepared.get('presentationVersion')) is int and prepared['presentationVersion'] in (1,2,3,4):
            from services.deep_research.citation_presentation import normalize as normalize_markers
            normalized,audit=normalize_markers(normalized,aliases,prepared['presentationQuotes'],
                **({'version':prepared['presentationVersion']} if prepared['presentationVersion'] in (2,3,4) else {}))
            if audit and presentation_audit is not None: presentation_audit.append(audit)
        valid.append(materialize_execution_claim(normalized))
    if coverage is not None and coverage_audit is not None:
        coverage['expandedRevisionIds']=[r['claimId'] for r in valid]
        coverage['unusableEditTargetIds']=[cid for cid in coverage['submittedEditIds'] if cid not in coverage['expandedRevisionIds']]
        coverage_audit.append(coverage)
    return valid


def factual_redraft_eligible(report):
    claims = report.get('claims', [])
    return bool(claims) and all(isinstance(c, dict) and c.get('kind') in {'reported','inference'}
        and not c.get('executionSpec') and not c.get('designRole')
        and c.get('designContractVersion') is None for c in claims)


def repair_rejected(report, verification, evidence, question, invoke, parse, *,
                    max_prompt_bytes=24000, metric_domains=None, batch_state=None, checkpoint=None,
                    current_budget=None, invoke_request=None, fact_redraft=False, requirement_context=(),
                    source_aware_redraft=False,comparison_reasoning=False,question_priority=False,concise_factual=False,factual_scope=False,declared_table_refs=False,strict_response=False,comparison_methodology=False,experimental_intent=False,compact_source_repair=False,shared_experiment_schema=False,experiment_evidence_context=None,experimental_edits=False,experimental_diagnostics=False,experimental_nested_tables=False,experimental_representation=False,experimental_coverage=False,citation_presentation_version=0,configuration_consistency_version=0,repair_evidence_packet_version=0,scheduling_version=0,answer_intents=None,scope_expression=False,defer_length_filter=False,table_identity_context=False,claim_check=False,required_scope_ids=(),compact_layout=False,ordinary_advice=False,task_sources=False,request_semantics=False,preserve_answers=False,target_goals=False):
    """One bounded revision round, split before dispatch when evidence cannot fit.

    At most three requests share full sibling design definitions. Successful
    batch drafts are checkpointed, never promoted without the independent
    verifier. A network/unknown error propagates; it does not create a retry.
    """
    from services.deep_research.contracts import digest, DeepResearchError
    from services.deep_research.repair_batches import split_repair_targets

    if type(preserve_answers) is not bool:raise ValueError('Invalid answer preservation policy')
    from services.deep_research.repair_goals import policy_version
    goal_version=policy_version(target_goals)
    if goal_version in (2,3,4) and not (fact_redraft and source_aware_redraft and concise_factual
            and compact_source_repair and factual_redraft_eligible(report)):
        raise ValueError('Point-scoped repair requires compact factual redrafting')
    if not (type(request_semantics) is bool or type(request_semantics) is int and request_semantics==2):raise ValueError('Invalid request semantics policy')
    if type(task_sources) is not bool:raise ValueError('Invalid task source disclosure policy')
    if type(ordinary_advice) is not bool:raise ValueError('Invalid ordinary advice repair policy')
    if ordinary_advice:
        from services.deep_research.general_advice import repair_eligible
        if not repair_eligible(report) or not (fact_redraft and source_aware_redraft and concise_factual and compact_source_repair):
            raise ValueError('Advice repair requires eligible source-aware clean redrafting')
    if type(compact_layout) is not bool:raise ValueError('Invalid factual compact layout policy')
    _validate_scope_ids(required_scope_ids,report,scope_expression)
    if type(defer_length_filter) is not bool:
        raise ValueError('Invalid deferred repair length policy')
    if type(claim_check) is not bool and not (type(claim_check) is int and claim_check in (4,5,6,7,8,9)):
        raise ValueError('Invalid claim check policy')
    if type(table_identity_context) is not bool and not (type(table_identity_context) is int and table_identity_context==2):
        raise ValueError('Invalid table identity context policy')

    if (type(scheduling_version) is not int or scheduling_version not in (0,1,2)
            or scheduling_version in (1,2) and not (shared_experiment_schema and experimental_edits)):
        raise ValueError('Unsupported experimental repair priority contract')
    deferred={row['claimId'] for row in verification.get('rejected',[]) if scheduling_version in (1,2)
        and (isinstance(row.get('rejectionAudit'),dict) and row['rejectionAudit'].get('bindingState')=='invalid'
             or scheduling_version==2 and row.get('executionState') in ('not_started','received_invalid'))}
    targets = {row['claimId'] for row in verification.get('rejected', [])}-deferred
    originals = [c for c in report.get('claims', []) if c.get('claimId') in targets]
    if not originals:
        return []
    if target_goals:
        from services.deep_research.repair_goals import bind
        try: bind(originals,requirement_context)
        except ValueError:
            if batch_state is not None:
                raise DeepResearchError('invalid_repair_plan','保存的修订目标与冻结问题不一致，不能重新发送。')
            return []  # No bound target means no provider dispatch, never a guessed whole-question repair.
    if type(repair_evidence_packet_version) is not int or repair_evidence_packet_version not in (0,1,2,3,4,5):
        raise ValueError('Unsupported experimental repair input contract')
    if repair_evidence_packet_version in (2,3,4,5) and not experimental_coverage:
        raise ValueError('Repair input2 requires response coverage')
    if experimental_coverage and not experimental_representation:
        raise ValueError('Experimental coverage requires representation-aware edits')
    if experimental_diagnostics and (not experimental_edits or not experimental_intent):
        raise ValueError('Experimental diagnostics require prospective field edits')
    if experimental_nested_tables and not experimental_diagnostics:
        raise ValueError('Nested experimental tables require diagnostic field edits')
    if experimental_representation and not experimental_nested_tables:
        raise ValueError('Experimental representation requires nested field edits')
    if type(configuration_consistency_version) is not int or configuration_consistency_version not in (0,2):
        raise ValueError('Unsupported configuration consistency contract')
    if type(citation_presentation_version) is not int or citation_presentation_version not in (0,2,3,4):
        raise ValueError('Unsupported citation presentation contract')
    identity = digest({**({'compactLayoutVersion':1} if compact_layout else {}),'report': report, 'verification': verification,
                       **({'requiredScopeIds':list(required_scope_ids)} if required_scope_ids else {}),
                       **({'claimCheckContractVersion':claim_check if type(claim_check) is int and claim_check in (4,5,6,7,8,9) else 1} if claim_check else {}),
                       **({'tableIdentityContextContractVersion':2 if type(table_identity_context) is int and table_identity_context==2 else 1} if table_identity_context else {}),
                       **({'deferLengthFilterVersion':1} if defer_length_filter else {}),
                       **({'scopeExpressionContractVersion':scope_expression if type(scope_expression) is int and scope_expression in (2,3,4) else 1} if scope_expression else {}),
                       **({'answerPointIntentContractVersion':1,'answerIntents':answer_intents} if answer_intents is not None else {}),
                       **({'experimentRepairPriorityContractVersion':scheduling_version} if scheduling_version in (1,2) else {}),
                       **({'experimentRepairInputContractVersion':repair_evidence_packet_version} if repair_evidence_packet_version in (1,2,3,4,5) else {}),
                       'evidence': evidence, 'question': question, 'metricDomains': metric_domains,
                       **({'citationPresentationContractVersion':citation_presentation_version} if citation_presentation_version in (2,3,4) else {}),
                       **({'configurationConsistencyContractVersion':2} if configuration_consistency_version==2 else {}),
                       **({'factRedraftContractVersion':3 if concise_factual else 2 if source_aware_redraft else 1,'requirementContext':requirement_context}
                          if fact_redraft else {}),
                       **({'comparisonReasoningContractVersion':1} if comparison_reasoning else {}),
                       **({'repairEvidencePriorityVersion':1} if question_priority else {}),
                       **({'factualScopeContractVersion':factual_scope if factual_scope in (2,3,4) else 1} if factual_scope else {}),
                       **({'tableReferencesContractVersion':4 if type(declared_table_refs) is int and declared_table_refs==4 else 1} if declared_table_refs else {}),
                       **({'recommendationRepairContractVersion':1} if ordinary_advice else {}),
                       **({'reportPresentationContractVersion':4} if task_sources else {}),
                       **({'answerPreservationContractVersion':1} if preserve_answers else {}),
                       **({'factualRepairGoalContractVersion':goal_version} if target_goals else {}),
                       **({'requestSemanticsContractVersion':2 if type(request_semantics) is int and request_semantics==2 else 1} if request_semantics else {}),
                       **({'repairResponseContractVersion':1} if strict_response else {}),
                       **({'factualRepairContractVersion':1} if compact_source_repair else {}),
                       **({'experimentRepairContractVersion':6 if experimental_coverage else 5 if experimental_representation else 4 if experimental_nested_tables else 3 if experimental_diagnostics else 2 if experimental_edits else 1} if shared_experiment_schema else {}),
                       **({'experimentEvidenceContractVersion':1,'experimentEvidenceContext':experiment_evidence_context}
                          if experiment_evidence_context is not None else {}),
                       **({'comparisonMethodologyVersion':1} if comparison_methodology else {}),
                       **({'experimentIntentContractVersion':experimental_intent if type(experimental_intent) is int and experimental_intent in (2,3) else 1}
                          if experimental_intent else {})})

    def prepare(ids, results=(), byte_limit=None):
        ids = set(ids)
        prior = {row['claimId']: row for row in results}
        siblings = [prior.get(c['claimId'], c) for c in originals if c['claimId'] not in ids]
        if scheduling_version in (1,2):
            siblings += [{**deepcopy(c),'reviewContextState':{'status':'unreviewed',
                'phase':'invalid_rejection_binding' if scheduling_version==1 else 'unverified_review'}}
                for c in report.get('claims',[]) if c.get('claimId') in deferred]
        subset = {'accepted': verification.get('accepted', []),
                  'rejected': [row for row in verification.get('rejected', []) if row['claimId'] in ids]}
        return _prepare_repair(report, subset, evidence, question,
            max_prompt_bytes=state['maxPromptBytes'] if byte_limit is None else byte_limit,
            metric_domains=metric_domains, draft_context=siblings, prior_revisions=results,
            compact_layout=compact_layout,fact_redraft=fact_redraft, requirement_context=requirement_context,source_aware_redraft=source_aware_redraft,
            **({'ordinary_advice':True} if ordinary_advice else {}),
            **({'task_sources':True} if task_sources else {}),
            **({'request_semantics':request_semantics} if request_semantics else {}),
            **({'preserve_answers':True} if preserve_answers else {}),
            **({'target_goals':target_goals} if target_goals else {}),
            **({'answer_intents':answer_intents} if answer_intents is not None else {}),
            **({'scope_expression':scope_expression} if scope_expression else {}),
            **({'required_scope_ids':[key for key in required_scope_ids if key in ids]} if required_scope_ids else {}),
            **({'table_identity_context':table_identity_context} if table_identity_context else {}),
            **({'claim_check':claim_check} if claim_check else {}),
            comparison_reasoning=comparison_reasoning,question_priority=question_priority,concise_factual=concise_factual,
            factual_scope=factual_scope,declared_table_refs=declared_table_refs,comparison_methodology=comparison_methodology,
            experimental_intent=experimental_intent,compact_source_repair=compact_source_repair,
            shared_experiment_schema=shared_experiment_schema,experiment_evidence_context=experiment_evidence_context,
            repair_evidence_packet_version=repair_evidence_packet_version,
            **({'experimental_edits':True} if experimental_edits else {}),
            **({'experimental_diagnostics':True} if experimental_diagnostics else {}),
            **({'experimental_nested_tables':True} if experimental_nested_tables else {}),
            **({'experimental_representation':True} if experimental_representation else {}),
            **({'experimental_coverage':True} if experimental_coverage else {}),
            **({'citation_presentation_version':citation_presentation_version} if citation_presentation_version in (2,3,4) else {}),
            **({'configuration_consistency_version':2} if configuration_consistency_version==2 else {}))

    state = deepcopy(batch_state) if batch_state is not None else {
        'version': 1, 'inputDigest': identity, 'maxPromptBytes': max_prompt_bytes,
        'batches': [[c['claimId'] for c in originals]], 'results': {}}
    if scheduling_version in (1,2) and batch_state is None:state['deferredReviewIds']=sorted(deferred)
    if (type(state.get('version')) is not int or state['version'] != 1 or state.get('inputDigest') != identity
            or type(state.get('maxPromptBytes')) is not int or not 0 <= state['maxPromptBytes'] <= (32000 if repair_evidence_packet_version in (4,5) else 24000)
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
            state['batches'] = split_repair_targets(originals,
                scientific_metrics=type(experimental_intent) is int and experimental_intent in (2,3),
                **({'structural_priority':True,'rejections':verification.get('rejected',[])} if scheduling_version in (1,2) else {}))
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
                    from services.deep_research.experiment_edits import OUTPUT_TOKENS
                    output = OUTPUT_TOKENS if experimental_edits else repair_batch_output_limit(len(group)) if invoke_request else 8192
                    cap = min(state['maxPromptBytes'], repair_prompt_byte_limit(current_budget(), output, **({'input_bytes':32000} if repair_evidence_packet_version in (4,5) else {}))) \
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
            presentation_audit=[]
            drafting_audit=[] if factual_scope or type(claim_check) is int and claim_check in (6,7,8,9) else None
            representation_audit=[] if experimental_representation else None
            scope_audit=[] if scope_expression else None
            coverage_audit=[] if experimental_coverage else None
            try:
                rows = _parse_repair_response(prepared, response, parse,presentation_audit,drafting_audit,
                                              strict_response=strict_response,
                                              **({'scope_audit':scope_audit} if scope_expression else {}),
                                              **({'representation_audit':representation_audit} if experimental_representation else {}),
                                              **({'coverage_audit':coverage_audit} if experimental_coverage else {}))
            except DeepResearchError as exc:
                if (exc.code!='invalid_repair_response' or exc.details.get('responseState')!='received_invalid'):
                    raise
                # A confirmed malformed response is settled, not an unknown call
                # and not an evidence-insufficiency finding. Checkpoint before
                # returning earlier drafts; never dispatch this batch again.
                state['results'][key]=[]
                state['responseError']={'code':exc.code,'responseState':'received_invalid','batch':index}
                state['stop']={'batch':index,'reason':'received_invalid'}
                state.pop('pending',None)
                if checkpoint:
                    checkpoint(deepcopy(state))
                break
            if scope_audit:
                state.setdefault('scopeExpressionAudit',{})[key]=scope_audit
            if drafting_audit:
                state.setdefault('factualDraftingAudit',{})[key]=drafting_audit
            if coverage_audit:
                state.setdefault('responseCoverageAudit',{})[key]=coverage_audit[0]
            if presentation_audit:
                state.setdefault('citationPresentationAudit',{})[key]=presentation_audit
            if representation_audit:
                # Representation attempts are not approvals; subsequent
                # permission/structure/science checks may still reject them.
                state.setdefault('representationNormalizationAudit',{})[key]=representation_audit
            state['results'][key] = rows
            state.pop('pending', None)
            if checkpoint:
                checkpoint(deepcopy(state))
        revised.extend(deepcopy(rows))
    if defer_length_filter:
        return revised  # The caller must compact and reverify before publication.
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


def _validate_scope_ids(ids,report,scope_expression):
    if (type(ids) not in (tuple,list) or any(not isinstance(key,str) or not key for key in ids)
            or len(set(ids))!=len(ids) or not set(ids)<={c.get('claimId') for c in report.get('claims',[])}
            or ids and not (type(scope_expression) is int and scope_expression in (1,2,3,4))):
        raise ValueError('Invalid required scope repair identities')
