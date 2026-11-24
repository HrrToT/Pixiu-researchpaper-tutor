"""Compile source-local comparison drafts into ordinary unverified claims.

This module owns layout and routing only. The existing factual, numerical,
scope, advice and whole-answer verifiers remain responsible for publication.
"""
from copy import deepcopy
import re

from services.deep_research.authored_body import decode
from services.deep_research.source_labels import source_display_title


_POINT_KEYS = {'kind', 'body', 'evidenceRefs', 'tableBindings', 'draftingBasis', 'detailLevel'}


class ComparisonDraftOverflow(ValueError):
    """A well-routed container exceeded its declared, pre-generation limit."""

    def __init__(self, received, limit):
        super().__init__('Comparison claim budget exceeded')
        self.received = received
        self.limit = limit


def plan_cells(requirements, sources, evidence, *, shared_axes=False, question=None, typed_roles=False,joint_reports=False,literal_axes=False,fixed_slots=False,unified_answers=False,local_goal_refs=False,measurement_display=False,separate_joint_deliverables=False,paired_protocol_notes=False,classify_standalone_joint=False, structured_test_first=False, structured_table_example=False, separate_example_boundary=False):
    """Keep every frozen obligation, with source-local citation permissions."""
    if type(measurement_display) is not bool or measurement_display and not local_goal_refs:
        raise ValueError('Measurement display requires explicit local-goal wire')
    if type(separate_joint_deliverables) is not bool or separate_joint_deliverables and not (joint_reports and local_goal_refs):
        raise ValueError('Separate joint deliverables require the joint local-goal wire')
    if type(paired_protocol_notes) is not bool or paired_protocol_notes and not separate_joint_deliverables:
        raise ValueError('Paired protocol notes require separate joint deliverables')
    if (type(shared_axes) is not bool or type(typed_roles) is not bool
            or (shared_axes or typed_roles) and not isinstance(question, str)):
        raise ValueError('Shared axes require the exact user question')
    if type(joint_reports) is not bool or joint_reports and not typed_roles:
        raise ValueError('Joint reports require typed roles')
    if type(literal_axes) is not bool or literal_axes and not typed_roles:
        raise ValueError('Literal axes require typed roles')
    if type(fixed_slots) is not bool or fixed_slots and not typed_roles:
        raise ValueError('Fixed slots require typed roles')
    if type(unified_answers) is not bool or unified_answers and not fixed_slots:
        raise ValueError('Unified answers require fixed comparison slots')
    if type(local_goal_refs) is not bool or local_goal_refs and not unified_answers:
        raise ValueError('Local goal references require unified answers')
    if not isinstance(sources, dict) or not sources or not isinstance(requirements, list):
        raise ValueError('Invalid comparison sources or requirements')
    if any(not isinstance(k, str) or not k or not isinstance(v, dict) for k, v in sources.items()):
        raise ValueError('Invalid comparison source registry')
    if not isinstance(evidence, list):
        raise ValueError('Invalid comparison evidence')
    rows = {}
    for row in evidence:
        if (not isinstance(row, dict) or not isinstance(row.get('evidenceId'), str)
                or not row['evidenceId'] or row['evidenceId'] in rows
                or not isinstance(row.get('source'), str) or row['source'] not in sources
                or not isinstance(row.get('obligations'), list)):
            raise ValueError('Invalid comparison evidence ownership')
        rows[row['evidenceId']] = deepcopy(row)
    cells, seen, axes, roles = [], set(), {}, {}
    for index, obligation in enumerate(requirements):
        if (not isinstance(obligation, dict) or not isinstance(obligation.get('obligationId'), str)
                or not obligation['obligationId'] or obligation['obligationId'] in seen
                or not isinstance(obligation.get('question'), str) or not obligation['question'].strip()):
            raise ValueError('Invalid comparison obligation')
        oid = obligation['obligationId']; seen.add(oid)
        required = obligation.get('requiredSources', [])
        if not isinstance(required, list) or any(not isinstance(v, str) for v in required):
            raise ValueError('Invalid comparison required identities')
        aliases = obligation.get('requiredSourceAliases')
        if aliases is None:
            aliases = ([alias for alias, source in sources.items() if set(required) & {
                source.get('workId'), source.get('sourceWorkId'), source.get('versionId'),
                source.get('sourceVersionId'), source.get('ownerMaterialId')}]
                if required else list(sources))
        if (not isinstance(aliases, list)
                or any(not isinstance(k, str) or k not in sources for k in aliases)
                or len(set(aliases)) != len(aliases)):
            raise ValueError('Invalid comparison source requirement')
        role = None
        if typed_roles:
            from services.deep_research.comparison_intent import validate_role
            role = validate_role(obligation, question)
            roles[oid] = {**deepcopy(role), 'obligationId': oid,
                          'question': obligation['question'], 'sourceAliases': list(aliases)}
            if role['kind'] != 'per_paper':
                continue
        # Split only an explicit short enumeration in the already-validated
        # literal role excerpt. Never guess axes from generated labels or
        # split conjunctions inside a dimension such as storage AND quality.
        parts=re.split('、',role['requestExcerpt']) if literal_axes and role else []
        parts=[p.strip() for p in parts]
        expanded=(2<=len(parts)<=6 and len(set(parts))==len(parts)
                  and all(p and len(p)<=40 and not re.search(r'[。！？；;\n]',p) for p in parts))
        labels=parts if expanded else [None]
        for part_index,label in enumerate(labels):
            axis = {}
            if shared_axes or typed_roles:
                excerpt = obligation.get('requestExcerpt')
                # Exact user text can align independently planned paper subtasks.
                shared = isinstance(excerpt, str) and bool(excerpt.strip()) and excerpt in question
                key = (('literal',label) if label is not None else
                       ('typed', role['label'], role['requestExcerpt']) if role else
                       ('request', excerpt) if shared else ('obligation', oid))
                if key not in axes: axes[key] = f'axis_{len(axes)}'
                axis = {'axisId': axes[key], 'axisTitle': label if label is not None else role['label'] if role else
                        excerpt if shared else obligation['question']}
            # An empty required mapping never permits borrowing a paper.
            for source in aliases:
                cells.append({'cellId': f'cell_{index}_{list(sources).index(source)}'+(f'_axis_{part_index}' if expanded else ''),
                          'obligationId': oid, 'question': obligation['question'], **axis,
                          'source': source,
                          'sourceTitle': source_display_title(sources[source].get('title'),
                                                             f'论文{list(sources).index(source)+1}'),
                          'evidenceIds': [eid for eid, row in rows.items() if row['source'] == source],
                          'preferredEvidenceIds': [eid for eid, row in rows.items()
                                                   if row['source'] == source and oid in row['obligations']]})
    result={'version': 3 if typed_roles else 2 if shared_axes else 1,
            **({'jointReports':True} if joint_reports else {}),
            **({'roles': roles} if typed_roles else {}), 'requirements': deepcopy(requirements),
            'sources': deepcopy(sources), 'evidence': rows, 'cells': cells}
    if fixed_slots:
        from services.deep_research.comparison_layout import apply_slots
        result=apply_slots(result,question)
    if unified_answers:result['answerWireVersion']=2 if local_goal_refs else 1
    if measurement_display:result['measurementDisplayVersion']=1
    if separate_joint_deliverables:
        from services.deep_research.comparison_joint_reports import split_joint_deliverables
        result['jointDeliverables'] = split_joint_deliverables(roles, requirements, question,
                                                                classify_standalone=classify_standalone_joint,
                                                                separate_example_boundary=separate_example_boundary)
    if paired_protocol_notes and result.get('jointDeliverables'):
        result['pairedProtocolNotes'] = True
    if structured_test_first and result.get('jointDeliverables'):
        result['structuredTestFirst'] = True
    if structured_table_example and result.get('jointDeliverables'):
        result['structuredTableExample'] = True
    return result


def _point(raw, cid, obligations, allowed, kinds, evidence):
    if (not isinstance(raw, dict) or set(raw) - _POINT_KEYS
            or not {'kind', 'body', 'evidenceRefs'} <= set(raw)
            or not isinstance(raw.get('kind'), str) or raw['kind'] not in kinds or not isinstance(raw['evidenceRefs'], list)
            or not raw['evidenceRefs'] or any(not isinstance(e, str) or e not in allowed
                                           for e in raw['evidenceRefs'])
            or len(set(raw['evidenceRefs'])) != len(raw['evidenceRefs'])):
        raise ValueError('invalid_point_or_source_permission')
    claim = {**deepcopy(raw), 'claimId': cid, 'obligationIds': list(obligations)}
    canonical = decode(claim, reasoning=True)
    # Reuse the public-prose guard, including protection for genuine source symbols.
    from services.deep_research.scope_expression import materialize
    from services.deep_research.prose_checks import leaks_internal_reference
    preview, _ = materialize(canonical, 5)
    support = [evidence[eid] for eid in raw['evidenceRefs']]
    if leaks_internal_reference(preview, support, table_aliases=True):
        raise ValueError('internal_reference_in_prose')
    return claim


def compile_cells(payload, plan, *, max_claims, table_registry=None):
    """Isolate bad cell points; no compiled claim has scientific approval."""
    bindings={};wire_audit=None
    if plan.get('answerWireVersion') in (1,2):
        from services.deep_research.comparison_wire import decode as decode_answers
        payload,wire_audit=decode_answers(payload,plan,table_registry or {},max_claims=max_claims)
    if plan.get('fixedSlots') is True:
        if type(max_claims) is not int or max_claims<1:raise ValueError('Invalid comparison point limit')
        from services.deep_research.comparison_layout import decode_slots
        payload,bindings=decode_slots(payload,plan,max_claims=max_claims)
    if (type(max_claims) is not int or max_claims < 1 or not isinstance(payload, dict)
            or set(payload) != {'cells', 'conclusions'}
            or not isinstance(payload['cells'], list) or not isinstance(payload['conclusions'], list)
            or type(plan.get('version')) is not int or plan['version'] not in (1,2,3)):
        raise ValueError('Invalid comparison draft')
    expected = {c['cellId']: c for c in plan['cells']}
    submitted = {}
    for cell in payload['cells']:
        if (not isinstance(cell, dict) or set(cell) != {'cellId', 'claims', 'unresolved'}
                or not isinstance(cell['cellId'], str) or cell['cellId'] not in expected
                or cell['cellId'] in submitted or not isinstance(cell['claims'], list)
                or type(cell['unresolved']) is not bool):
            raise ValueError('Invalid comparison cell identity')
        submitted[cell['cellId']] = cell
    count = sum(len(c['claims']) for c in submitted.values()) + len(payload['conclusions'])
    if count > max_claims:
        raise ComparisonDraftOverflow(count, max_claims)
    claims, layout, errors = [], [], []
    for index, cell in enumerate(plan['cells']):
        raw = submitted.get(cell['cellId'])
        entry = {**deepcopy(cell), 'claimIds': [], 'unresolved': raw is None or raw['unresolved']}
        goals=bindings.get(cell['cellId'],[cell['obligationId']])
        if 'allowedObligationIds' in cell:
            entry['obligationIds']=goals
            if goals:entry['obligationId']=goals[0]
        for ordinal, point in enumerate(raw['claims'] if raw else []):
            cid = f'cmp_{index}_{ordinal}'
            try:
                claim = _point(point, cid, goals, set(cell['evidenceIds']),
                               {'reported', 'inference'}, plan['evidence'])
            except ValueError as exc:
                errors.append({'cellId': cell['cellId'], 'pointIndex': ordinal, 'reason': str(exc)})
                entry['unresolved'] = True
                continue
            claims.append(claim); entry['claimIds'].append(cid)
        if not entry['claimIds']: entry['unresolved'] = True
        layout.append(entry)
    typed = plan['version'] == 3
    oids = ({oid for oid, role in plan['roles'].items() if role['kind'] == 'joint'}
            if typed else {o['obligationId'] for o in plan['requirements']})
    conclusion_ids, covered_joint_goals = [], set()
    for index, point in enumerate(payload['conclusions']):
        cid = f'cmp_conclusion_{index}'
        try:
            if (not isinstance(point, dict) or set(point) != {'claim', 'obligationIds'}
                    or not isinstance(point['obligationIds'], list) or not point['obligationIds']
                    or any(not isinstance(k, str) or k not in oids for k in point['obligationIds'])):
                raise ValueError('invalid_conclusion_obligations')
            aliases = {alias for oid in point['obligationIds'] for alias in plan['roles'][oid]['sourceAliases']} if typed else None
            permitted = ({eid for eid, row in plan['evidence'].items() if row['source'] in aliases}
                         if typed else set(plan['evidence']))
            claim = _point(point['claim'], cid, point['obligationIds'], permitted,
                           {'inference', 'proposal', 'suggestion'} | ({'reported'} if typed and plan.get('jointReports') is True else set()), plan['evidence'])
        except ValueError as exc:
            errors.append({'conclusionIndex': index, 'reason': str(exc)}); continue
        claims.append(claim); conclusion_ids.append(cid)
        covered_joint_goals.update(point['obligationIds'])
    if len(claims) > max_claims:
        raise ValueError('Comparison claim budget exceeded')
    sections = [{'title': '比较条目', 'claimIds': [cid for row in layout for cid in row['claimIds']]}]
    if conclusion_ids: sections.append({'title': '综合判断与建议', 'claimIds': conclusion_ids})
    unresolved = [o['obligationId'] for o in plan['requirements']
                  if not any(c['obligationId'] == o['obligationId'] for c in layout)
                  or any(c['obligationId'] == o['obligationId'] and c['unresolved'] for c in layout)]
    if typed:
        unresolved = [oid for oid in unresolved if oid not in covered_joint_goals]
    if plan.get('fixedSlots') is True:
        # IDs record routing only; final semantic coverage still checks the
        # complete question, criteria and every rendered cell.
        routed={oid for claim in claims for oid in claim.get('obligationIds',[])}
        missing={oid for row in layout if row['unresolved'] for oid in
                 (row.get('obligationIds') or row.get('allowedObligationIds',[row['obligationId']]))}
        unresolved=[o['obligationId'] for o in plan['requirements'] if o['obligationId'] not in routed or o['obligationId'] in missing]
    return {**({'answerWireAudit':wire_audit} if wire_audit is not None else {}),**({'layoutVersion': plan['version']} if plan['version'] in (2,3) else {}),
            **({'fixedSlots':True} if plan.get('fixedSlots') is True else {}),
            **({'jointReports':True} if typed and plan.get('jointReports') is True else {}),
            **({'jointDeliverables':deepcopy(plan['jointDeliverables'])} if plan.get('jointDeliverables') else {}),
            **({'jointGoals': [deepcopy(role) for role in plan['roles'].values() if role['kind'] == 'joint']}
               if typed else {}),
            'report': {'sections': sections, 'claims': claims}, 'layout': layout,
            'errors': errors, 'unresolvedObligationIds': unresolved,
            'verification': 'unchecked'}


def partition_source_bound_claims(claims, draft, evidence):
    """Recheck paper/version ownership after edits; do not approve any text."""
    if draft is None:
        # Budget/cancellation can stop synthesis before a cell draft exists.
        # An absent draft cannot authorize even a purported joint conclusion.
        return [], [{'claimId': claim['claimId'], 'reason': 'comparison_cell_draft_missing'}
                    for claim in claims]
    by_id = {e['evidenceId']: e for e in evidence}
    owners = {cid: cell['source'] for cell in draft['layout'] for cid in cell['claimIds']}
    typed = draft.get('layoutVersion') == 3
    goals = {cid: cell.get('obligationIds',[cell['obligationId']]) for cell in draft['layout'] for cid in cell['claimIds']} if typed else {}
    retained, rejected = [], []
    for claim in claims:
        if 'benchmarkExampleClaimId' in draft:
            from services.deep_research.comparison_joint_reports import benchmark_binding_error
            error = benchmark_binding_error(claim, draft)
            if error:
                rejected.append({'claimId': claim['claimId'], 'reason': error,
                    'detail': ('基准数字只放在一个同表配对示例中。分栏保留原文支持的定性结论；'
                               '配对示例只使用同一数据组内两行的同名指标。')})
                continue
        alias = owners.get(claim['claimId'])
        if alias is None:
            if typed:
                joint = {goal['obligationId']: goal for goal in draft['jointGoals']}
                targets = claim.get('obligationIds')
                refs = claim.get('evidenceRefs')
                valid = (isinstance(targets,list) and bool(targets)
                         and all(isinstance(oid,str) and oid in joint for oid in targets))
                aliases = {a for oid in targets for a in joint[oid]['sourceAliases']} if valid else set()
                pairs = set()
                for a in aliases:
                    source = draft['sources'].get(a,{})
                    work = source.get('workId',source.get('sourceWorkId'))
                    version = source.get('versionId',source.get('sourceVersionId'))
                    if isinstance(work,str) and work and isinstance(version,str) and version:
                        pairs.add((work,version))
                valid = (valid and isinstance(refs,list) and bool(refs)
                         and all(isinstance(ref,str) and ref in by_id
                             and (by_id[ref].get('sourceWorkId'),by_id[ref].get('sourceVersionId')) in pairs
                             for ref in refs))
                if not valid:
                    rejected.append({'claimId':claim['claimId'],'reason':'comparison_joint_scope_mismatch'})
                    continue
            retained.append(deepcopy(claim))  # Joint conclusions still use normal verification.
            continue
        if typed and claim.get('obligationIds') != goals[claim['claimId']]:
            rejected.append({'claimId':claim['claimId'],'reason':'comparison_cell_goal_mismatch'})
            continue
        source = draft['sources'][alias]
        work = source.get('workId', source.get('sourceWorkId'))
        version = source.get('versionId', source.get('sourceVersionId'))
        refs = claim.get('evidenceRefs')
        if (not isinstance(work, str) or not work or not isinstance(version, str) or not version
                or not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or ref not in by_id
                    or by_id[ref].get('sourceWorkId') != work
                    or by_id[ref].get('sourceVersionId') != version for ref in refs)):
            rejected.append({'claimId': claim['claimId'], 'reason': 'comparison_cell_source_mismatch'})
        else:
            retained.append(deepcopy(claim))
    return retained, rejected
