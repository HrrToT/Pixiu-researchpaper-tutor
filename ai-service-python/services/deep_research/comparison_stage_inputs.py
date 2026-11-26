"""Build complete source-local comparison inputs before any model dispatch.

New comparison planning version6 selects this module. Preparation grants no coverage,
scientific approval, provider token estimate or end-to-end latency guarantee.
"""
from copy import deepcopy
from math import ceil

from services.deep_research.contracts import BudgetExhaustedError, DeepResearchError, digest
from services.deep_research.comparison_cells import plan_cells
from services.deep_research.comparison_cross_paper_boundary import scopes as paper_scopes
from services.deep_research.comparison_wire import example_pairs, render, targets, table_catalog, stage_table_catalog
from services.deep_research.request_context import effective_question
from services.deep_research.synthesis_evidence import fit_premises


def enabled(record):
    from services.deep_research.comparison_generation import enabled as comparison_enabled
    return (type(record.get('comparisonPlanningContractVersion')) is int
            and record['comparisonPlanningContractVersion'] == 6
            and type(record.get('comparisonReviewBatchContractVersion')) is int
            and record['comparisonReviewBatchContractVersion'] == 2
            and comparison_enabled(record))


def minimum_completion_calls(stage_count, target_count):
    # Generation, factual-review batches, a whole-answer audit, and one
    # edit/recheck/re-audit cycle. Additional advice or review may need more.
    return stage_count + ceil(target_count / 3) + 1 + 3


def exploration_completion_calls(record):
    """Estimate the stage admission floor from the full plan, before acquiring more evidence."""
    from services.deep_research.comparison_generation import planning_options
    from services.deep_research.comparison_measurement_display import isolated
    from services.deep_research.design_drafting import synthesis_obligations

    version = record.get('comparisonExplorationContractVersion')
    if type(version) is not int or version != 1:
        return 0
    if not enabled(record) or not isolated(record):
        return 0
    state = record.get('state', {})
    requirements = synthesis_obligations(state.get('plan', []))
    if not requirements:
        return 0
    identities = {}
    for material in record.get('materials', []):
        work = material.get('workId') or material.get('materialId')
        if work:
            identities[(work, material.get('versionId', ''))] = material.get('title', '')
    if record.get('sourcePolicy', {}).get('mode') in ('academic_external', 'external_only'):
        for source in state.get('evidence', []):
            work = source.get('sourceWorkId')
            if work:
                identities.setdefault((work, source.get('sourceVersionId', '')), source.get('sourceTitle', ''))
    if not identities:
        return 0
    sources = {f'P{i}': {'workId': work, 'versionId': version, 'title': title}
               for i, ((work, version), title) in enumerate(identities.items(), start=1)}
    question = effective_question(record)
    planned = targets(plan_cells(requirements, sources, [], **planning_options(record, question)))
    paper_stages = {target['source'] for target in planned if target['role'] == 'paper_cell'}
    joint_stage = any(target['role'] == 'joint' for target in planned)
    return minimum_completion_calls(len(paper_stages) + joint_stage, len(planned)) if planned else 0


def prepare(record, requirements, sources, rows, tables, bundles, aliases, *,
            max_input_bytes=32000, character_limit=None, merge_joint=True):
    """Retain all candidates until separate <=20-row stage allocations finish.

    Every frozen premise bundle belongs to exactly one stage. A missing bundle
    refuses preparation rather than dispatching a knowingly incomplete input.
    """
    if type(max_input_bytes) is not int or not 1 <= max_input_bytes <= 32000:
        raise ValueError('Invalid comparison stage input window')
    if type(merge_joint) is not bool:
        raise ValueError('Invalid comparison stage merge policy')
    from services.deep_research.comparison_measurement_display import (
        isolated, ISOLATED_INPUT_BYTES, joint_comparison_delivery, paired_protocol_notes,
        preserve_numeric_example, separate_joint_deliverables)
    if isolated(record):
        # Fixed at creation by the frozen authoring profile, never shrunk with
        # current usage. Mandatory bundles/context must still fit in full.
        merge_joint = False
        max_input_bytes = min(max_input_bytes, ISOLATED_INPUT_BYTES)
    question = effective_question(record)
    reverse = {value: key for key, value in aliases.items()}
    if (len(reverse) != len(aliases) or len({r['evidenceId'] for r in rows}) != len(rows)
            or any(r['evidenceId'] not in aliases for r in rows)):
        raise ValueError('Invalid comparison stage evidence aliases')
    plan_options = dict(shared_axes=True, typed_roles=True, joint_reports=True,
                        question=question, literal_axes=True, fixed_slots=True,
                        unified_answers=True, local_goal_refs=True,
                        literal_goal_bindings=record.get('comparisonLiteralAxisGoalVersion') == 1)
    from services.deep_research.comparison_measurement_display import enabled as measurement_display
    from services.deep_research.comparison_joint_reports import benchmark_example_owner
    from services.deep_research.measurement_table_navigation import benchmark_metric
    if measurement_display(record):
        plan_options['measurement_display'] = True
    if separate_joint_deliverables(record):
        plan_options['separate_joint_deliverables'] = True
    if paired_protocol_notes(record):
        plan_options['paired_protocol_notes'] = True
    if record.get('comparisonJointReportsContractVersion') in (11, 12, 13, 14, 15, 16):
        plan_options['structured_test_first'] = True
    if record.get('recommendationReviewContractVersion') == 5:
        plan_options['direct_device_memory'] = True
    if record.get('comparisonJointReportsContractVersion') in (12, 13, 14, 15, 16):
        plan_options['structured_table_example'] = True
    if record.get('comparisonJointReportsContractVersion') in (13, 14, 15, 16):
        plan_options['separate_example_boundary'] = True
    if record.get('comparisonJointReportsContractVersion') in (14, 15, 16):
        plan_options['group_example_criteria'] = True
    if record.get('comparisonJointReportsContractVersion') == 16:
        plan_options['scoped_example_text'] = 2 if record.get('comparisonBenchmarkSpeedScopeContractVersion') in (2, 3) else True
    if record.get('comparisonCrossPaperBoundaryContractVersion') in (2, 3, 4, 5):
        plan_options['split_speed_and_advice'] = True
    if preserve_numeric_example(record):
        plan_options['classify_standalone_joint'] = True
    full_plan = plan_cells(requirements, sources, rows, **plan_options)
    all_targets = targets(full_plan)
    paper_subjects = paper_scopes(record, full_plan, all_targets, question=question)
    example_owner = benchmark_example_owner(record, full_plan)
    by_id = {r['evidenceId']: r for r in rows}
    wire_bundles = []
    for original in bundles:
        bundle = deepcopy(original)
        bundle['evidenceIds'] = [reverse.get(eid, eid) for eid in bundle['evidenceIds']]
        if not bundle['evidenceIds'] or any(eid not in by_id for eid in bundle['evidenceIds']):
            raise DeepResearchError('comparison_stage_evidence_missing', '必要比较证据不完整，尚未发送。')
        if bundle['obligationId'] not in full_plan['roles']:
            raise ValueError('Unknown comparison stage obligation')
        if 'requiredContextByEvidenceId' in bundle:
            bundle['requiredContextByEvidenceId'] = {
                reverse.get(eid, eid): context for eid, context in bundle['requiredContextByEvidenceId'].items()}
        wire_bundles.append(bundle)
    paper_targets = {alias: [t['targetId'] for t in all_targets
                            if t['role'] == 'paper_cell' and t['source'] == alias]
                     for alias in sources}
    stage_ids = [alias for alias in sources if paper_targets[alias]]
    joint_targets = [t['targetId'] for t in all_targets if t['role'] == 'joint']
    if joint_targets:
        stage_ids.append('joint')
    assigned = {key: [] for key in stage_ids}
    version = record.get('comparisonJointReportsContractVersion')
    known_protocols = None
    if version in (10, 11, 12, 13, 14, 15, 16) and joint_targets and paired_protocol_notes(record):
        _, catalog = table_catalog(full_plan, tables)
        known_protocols = {table['evidenceId']: table['matchedProtocol'] for table in catalog
                           if 'matchedProtocol' in table}
    for bundle in wire_bundles:
        role = full_plan['roles'][bundle['obligationId']]['kind']
        owners = {by_id[eid]['source'] for eid in bundle['evidenceIds']}
        if role == 'joint':
            scope = 'joint'
        elif len(owners) != 1:
            raise DeepResearchError('comparison_stage_bundle_ownership', '单论文必要证据混合来源，尚未发送。')
        else:
            scope = next(iter(owners))
            if scope not in assigned and role == 'supporting':
                scope = 'joint'
        if scope not in assigned:
            raise DeepResearchError('comparison_stage_target_missing', '必要比较目标未能分配，尚未发送。')
        assigned[scope].append(bundle)
    contexts = {eid: context for b in wire_bundles
                for eid, context in b.get('requiredContextByEvidenceId', {}).items()}
    def build_stage(scope, members):
        include_joint = 'joint' in members
        own = rows if include_joint else [r for r in rows if r['source'] in members]
        if include_joint and joint_comparison_delivery(record):
            from services.deep_research.comparison_joint_reports import (
                comparison_protocol_priority, evaluation_protocols_enabled, joint_numeric_example,
                deployment_memory_context_enabled, deployment_memory_priority,
            )
            examples = joint_numeric_example(full_plan['roles'], question)
            protocols = (comparison_protocol_priority(own, all_targets, reported_platform=evaluation_protocols_enabled(record),
                         explicit_targets=record.get('comparisonEvaluationProtocolVersion') in (3, 4))
                         if version in (4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16) else set())
            if deployment_memory_context_enabled(record):
                protocols.update(deployment_memory_priority(own, all_targets))
            if examples or protocols:
                # Mandatory premises are fitted first. Offer the narrow
                # protocol passages before optional table inventories.
                own = sorted(own, key=lambda row: (
                    row['evidenceId'] not in protocols,
                    examples and not (row.get('tableData') or row.get('tableDataRef')),
                ))
        target_ids = [key for member in members
                      for key in (joint_targets if member == 'joint' else paper_targets[member])]
        required = [bundle for member in members for bundle in assigned[member]]
        visible_protocols = known_protocols if include_joint else None
        optional_pairs = [(protocol['noteEvidenceId'], table_id)
                          for table_id, protocol in (visible_protocols or {}).items()]
        def render_stage(selected):
            plan = plan_cells(requirements, sources, selected, **plan_options)
            return render(record, question, plan, tables, character_limit, len(target_ids),
                          source_scope=tuple(members), known_protocols=visible_protocols)
        prompt, selected, missing = fit_premises(own, render_stage, required,
            max_bytes=max_input_bytes, omit_optional_table_data=False, required_contexts=contexts,
            optional_bundles=optional_pairs)
        if missing or not selected:
            raise DeepResearchError('comparison_stage_evidence_capacity',
                                    '完整比较阶段证据超出输入窗口，尚未发送。')
        supplied = [r['evidenceId'] for r in selected]
        selected_plan = plan_cells(requirements, sources, selected, **plan_options)
        visible_cells, catalog = table_catalog(selected_plan, tables)
        if version in (9, 10, 11, 12, 13, 14, 15, 16):
            projected = stage_table_catalog(catalog, joint=include_joint,
                reserved_benchmark=example_owner is not None, known_protocols=visible_protocols)
            visible_refs = {ref for table in projected for row in table['rows'] for ref, _ in row[2]}
            visible_cells = {ref: value for ref, value in visible_cells.items() if ref in visible_refs}
        permissions = {t['targetId']: t['evidenceIds'] for t in targets(selected_plan)
                       if t['targetId'] in target_ids}
        pairs = (example_pairs(projected, permissions[example_owner])
                 if version in (15, 16) and scope == 'joint' and example_owner in permissions else {})
        stage_papers = {key: paper_subjects[key] for key in target_ids if key in paper_subjects}
        stage = {'stageId': scope, 'targetIds': target_ids, 'maxPoints': len(target_ids),
                 'prompt': prompt, 'inputBytes': len(prompt.encode('utf-8')),
                 'requiredBundleCount': len(required), 'suppliedEvidenceIds': supplied,
                 'requiredEvidenceIds': sorted({eid for b in required for eid in b['evidenceIds']}),
                 'allowedEvidenceByTarget': permissions,
                 'allowedCellsByTarget': {key: [ref for ref, value in visible_cells.items()
                                               if value['binding']['evidenceId'] in allowed
                                               and (example_owner is None or key == example_owner
                                                    or not benchmark_metric(value['binding']['metric']))]
                                          for key, allowed in permissions.items()},
                 **({'examplePairsByTarget': {example_owner: pairs}} if pairs else {}),
                 **({'paperSubjectsByTarget': stage_papers} if stage_papers else {}),
                 'scientificApproval': False}
        stage['inputDigest'] = digest(stage)
        return stage
    separate = {key: build_stage(key, [key]) for key in stage_ids}
    stages = list(separate.values())
    if merge_joint and 'joint' in separate:
        choices = []
        for source in sources:
            if source not in separate:
                continue
            try:
                merged = build_stage(source + '_joint', [source, 'joint'])
            except DeepResearchError as exc:
                if exc.code != 'comparison_stage_evidence_capacity':
                    raise
                continue
            except ValueError as exc:
                if str(exc) != 'prompt_fixed_content_too_large':
                    raise
                continue
            candidate = [value for key, value in separate.items() if key not in {source, 'joint'}] + [merged]
            choices.append(candidate)
        if choices:
            stages = min(choices, key=lambda group: sum(s['inputBytes'] for s in group))
    retained = {eid for stage in stages for eid in stage['suppliedEvidenceIds']}
    if not stages or sum(len(v) for v in assigned.values()) != len(wire_bundles):
        raise ValueError('Comparison stage allocation is incomplete')
    budget = record.get('budget', {})
    if any(type(budget.get(k)) is not int or budget[k] < 0
           for k in ('maxModelCalls', 'modelCalls', 'reservedModelCalls')):
        raise ValueError('Invalid comparison stage call budget')
    remaining = budget['maxModelCalls'] - budget['modelCalls'] - budget['reservedModelCalls']
    call_floor = minimum_completion_calls(len(stages), len(all_targets))
    snapshot = {'version': 1, 'maxInputBytes':max_input_bytes, 'question': str(question),
                'questionLayers': list(getattr(question,'instruction_layers',(str(question),))),
                'requirements': deepcopy(requirements),
                'sources': deepcopy(sources), 'aliases': {eid: aliases[eid] for eid in sorted(retained)},
                'rows': [deepcopy(row) for row in rows if row['evidenceId'] in retained],
                'tables': deepcopy(tables), 'stages': stages,
                'admission': {'remainingModelCalls': remaining, 'callLowerBound': call_floor,
                              'additionalAdviceOrRecheckCallsMayBeRequired': True,
                              'providerTokensAndWallClockFitEstablished': False,
                              'generationInputBytesTotal': sum(s['inputBytes'] for s in stages)},
                'sourcePolicy': deepcopy(record.get('sourcePolicy')),
                'contracts': {k: deepcopy(v) for k, v in record.items() if k.endswith('ContractVersion')},
                'budgetLimits': {k: budget.get(k) for k in ('maxModelCalls','maxTokens','maxWallClockSeconds')},
                'allFrozenPremiseBundlesRetained': True, 'scientificApproval': False}
    snapshot['inputDigest'] = digest({k: v for k, v in snapshot.items() if k != 'admission'})
    prior = record.get('state', {}).get('comparisonStageInput')
    if prior is not None:
        if (not isinstance(prior, dict) or prior.get('scientificApproval') is not False
                or prior.get('inputDigest') != snapshot['inputDigest']
                or digest({k: v for k, v in prior.items() if k not in {'admission','inputDigest'}})
                   != snapshot['inputDigest']):
            raise DeepResearchError('invalid_comparison_stage_input', '已保存比较输入或身份改变，不能重发。')
        return deepcopy(prior)
    if remaining < call_floor:
        raise BudgetExhaustedError('comparisonStageCalls', remaining, call_floor)
    return snapshot
