"""Compile source-local comparison drafts into ordinary unverified claims.

This module owns layout and routing only. The existing factual, numerical,
scope, advice and whole-answer verifiers remain responsible for publication.
"""
from copy import deepcopy

from services.deep_research.authored_body import decode
from services.deep_research.source_labels import source_display_title


_POINT_KEYS = {'kind', 'body', 'evidenceRefs', 'tableBindings', 'draftingBasis', 'detailLevel'}


def plan_cells(requirements, sources, evidence, *, shared_axes=False, question=None):
    """Keep every frozen obligation, with source-local citation permissions."""
    if type(shared_axes) is not bool or shared_axes and not isinstance(question, str):
        raise ValueError('Shared axes require the exact user question')
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
    cells, seen, axes = [], set(), {}
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
        axis = {}
        if shared_axes:
            excerpt = obligation.get('requestExcerpt')
            # Exact user text can align independently planned paper subtasks.
            # Do not infer semantic equivalence from similar generated questions.
            shared = isinstance(excerpt, str) and bool(excerpt.strip()) and excerpt in question
            key = ('request', excerpt) if shared else ('obligation', oid)
            if key not in axes: axes[key] = f'axis_{len(axes)}'
            axis = {'axisId': axes[key], 'axisTitle': excerpt if shared else obligation['question']}
        # An empty required mapping is unresolved, never permission to borrow a paper.
        for source in aliases:
            cells.append({'cellId': f'cell_{index}_{list(sources).index(source)}',
                          'obligationId': oid, 'question': obligation['question'], **axis,
                          'source': source,
                          'sourceTitle': source_display_title(sources[source].get('title'),
                                                             f'论文{list(sources).index(source)+1}'),
                          'evidenceIds': [eid for eid, row in rows.items() if row['source'] == source],
                          'preferredEvidenceIds': [eid for eid, row in rows.items()
                                                   if row['source'] == source and oid in row['obligations']]})
    return {'version': 2 if shared_axes else 1, 'requirements': deepcopy(requirements),
            'sources': deepcopy(sources), 'evidence': rows, 'cells': cells}


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


def compile_cells(payload, plan, *, max_claims):
    """Isolate bad cell points; no compiled claim has scientific approval."""
    if (type(max_claims) is not int or max_claims < 1 or not isinstance(payload, dict)
            or set(payload) != {'cells', 'conclusions'}
            or not isinstance(payload['cells'], list) or not isinstance(payload['conclusions'], list)
            or type(plan.get('version')) is not int or plan['version'] not in (1,2)):
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
    if sum(len(c['claims']) for c in submitted.values()) + len(payload['conclusions']) > max_claims:
        raise ValueError('Comparison claim budget exceeded')
    claims, layout, errors = [], [], []
    for index, cell in enumerate(plan['cells']):
        raw = submitted.get(cell['cellId'])
        entry = {**deepcopy(cell), 'claimIds': [], 'unresolved': raw is None or raw['unresolved']}
        for ordinal, point in enumerate(raw['claims'] if raw else []):
            cid = f'cmp_{index}_{ordinal}'
            try:
                claim = _point(point, cid, [cell['obligationId']], set(cell['evidenceIds']),
                               {'reported', 'inference'}, plan['evidence'])
            except ValueError as exc:
                errors.append({'cellId': cell['cellId'], 'pointIndex': ordinal, 'reason': str(exc)})
                entry['unresolved'] = True
                continue
            claims.append(claim); entry['claimIds'].append(cid)
        if not entry['claimIds']: entry['unresolved'] = True
        layout.append(entry)
    oids = {o['obligationId'] for o in plan['requirements']}
    conclusion_ids = []
    for index, point in enumerate(payload['conclusions']):
        cid = f'cmp_conclusion_{index}'
        try:
            if (not isinstance(point, dict) or set(point) != {'claim', 'obligationIds'}
                    or not isinstance(point['obligationIds'], list) or not point['obligationIds']
                    or any(not isinstance(k, str) or k not in oids for k in point['obligationIds'])):
                raise ValueError('invalid_conclusion_obligations')
            claim = _point(point['claim'], cid, point['obligationIds'], set(plan['evidence']),
                           {'inference', 'proposal', 'suggestion'}, plan['evidence'])
        except ValueError as exc:
            errors.append({'conclusionIndex': index, 'reason': str(exc)}); continue
        claims.append(claim); conclusion_ids.append(cid)
    if len(claims) > max_claims:
        raise ValueError('Comparison claim budget exceeded')
    sections = [{'title': '比较条目', 'claimIds': [cid for row in layout for cid in row['claimIds']]}]
    if conclusion_ids: sections.append({'title': '综合判断与建议', 'claimIds': conclusion_ids})
    return {**({'layoutVersion': 2} if plan['version'] == 2 else {}),
            'report': {'sections': sections, 'claims': claims}, 'layout': layout,
            'errors': errors, 'unresolvedObligationIds': [o['obligationId'] for o in plan['requirements']
                if not any(c['obligationId'] == o['obligationId'] for c in layout)
                or any(c['obligationId'] == o['obligationId'] and c['unresolved'] for c in layout)],
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
    retained, rejected = [], []
    for claim in claims:
        alias = owners.get(claim['claimId'])
        if alias is None:
            retained.append(deepcopy(claim))  # Joint conclusions still use normal verification.
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
