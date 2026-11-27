"""Fit complete proposals and frozen evidence obligations to a review window."""


def fit_accounted_evidence(record, data, aliases, proposal, build_request, limit, *, feedback_refs=(),
                           required_only=False):
    rows = data['evidence']

    def build(selected):
        packet_ids = {row.get('tableDataRef') for row in selected}
        scoped = {**data, 'evidence':selected, 'tables':{key:value for key,value in data['tables'].items()
                                                     if key in packet_ids}}
        request, size = build_request(scoped)
        return request, size, [row['evidenceId'] for row in selected]

    request, size = build_request(data)
    supplied = [row['evidenceId'] for row in rows]
    if size <= limit and not required_only:
        return request, size, supplied
    allocation = record.get('state', {}).get('sharedExperimentMaterialAllocation', {})
    required = allocation.get('requiredEvidenceIds')
    allocated = allocation.get('suppliedEvidenceIds')
    if (not isinstance(required, list) or not allocation.get('allFrozenPremiseBundlesRetained')
            or not isinstance(allocated, list) or any(not isinstance(value, str) for value in [*allocated, *required])
            or sorted(allocated) != sorted(aliases.values())
            or not set(required) <= set(aliases.values())):
        return request, size, supplied
    cited = {ref for fact in proposal['sourceFacts'] for ref in fact['evidenceRefs']}
    needed = cited | set(feedback_refs) | {ref for ref, original in aliases.items() if original in required}
    if not needed or not needed <= set(supplied):
        return request, size, supplied
    chosen = {i for i, row in enumerate(rows) if row['evidenceId'] in needed}
    compact = build([rows[i] for i in sorted(chosen)])
    if required_only or compact[1] > limit:
        return compact
    for position in range(len(rows)):
        if position in chosen:
            continue
        candidate = build([rows[i] for i in sorted(chosen | {position})])
        if candidate[1] <= limit:
            chosen.add(position)
            compact = candidate
    return compact


def partition_review(record, data, aliases, proposal, build_request, limit):
    """Retain the complete proposal in both parts; partition checks and evidence duties."""
    if not data['factChecks'] or not data['sectionChecks'] or not data['humanChecks']:
        return []
    # The fact part carries every cited original. The scheme-level part
    # retains all frozen premise bundles and as much additional evidence as fits.
    facts = {**data, 'requirements': [], 'sectionChecks': [], 'humanChecks': []}
    cited = {ref for fact in proposal['sourceFacts'] for ref in fact['evidenceRefs']}
    facts['evidence'] = [row for row in data['evidence'] if row['evidenceId'] in cited]
    packets = {row.get('tableDataRef') for row in facts['evidence']}
    facts['tables'] = {key: value for key, value in data['tables'].items() if key in packets}
    if {row['evidenceId'] for row in facts['evidence']} != cited:
        return []
    first_request, first_size = build_request(facts)
    if first_size > limit:
        return []
    plan = {**data, 'factChecks': []}
    second_request, second_size, second_refs = fit_accounted_evidence(
        record, plan, aliases, {**proposal, 'sourceFacts': []}, build_request, limit)
    if second_size > limit:
        return []
    return [
        {'request': first_request, 'inputBytes': first_size,
         'checkIds': [entry[0] for entry in data['factChecks']],
         'suppliedEvidenceAliases': [row['evidenceId'] for row in facts['evidence']]},
        {'request': second_request, 'inputBytes': second_size,
         'checkIds': [entry[0] for entry in [*data['sectionChecks'], *data['humanChecks']]],
         'suppliedEvidenceAliases': second_refs},
    ]


def _requirements_for_checks(requirements, checks):
    wanted = {(oid, cid) for _, oid, cid in checks}
    selected = []
    for row in requirements:
        oid = row['obligationId']
        if (oid, 'whole') in wanted:
            selected.append(row)
            continue
        criteria = [c for c in row.get('completionCriteria', []) if (oid, c['criterionId']) in wanted]
        if criteria:
            selected.append({**row, 'completionCriteria': criteria})
    return selected


def partition_bounded_review(record, data, aliases, proposal, build_request, limit, max_checks, *, scoped=False,
                             required_design_evidence_only=False, fit_check_count=False, pack_design_checks=False):
    """Keep the full design in design reviews; facts may use their own source packet."""
    fact_sources = {fact['id']: set(fact['evidenceRefs']) for fact in proposal['sourceFacts']}
    batches = []
    for key in ('factChecks', 'sectionChecks', 'humanChecks'):
        checks = data[key]
        def build_part(selected):
            packet = {**data, 'factChecks': [], 'sectionChecks': [], 'humanChecks': [], key: selected}
            if key == 'factChecks':
                cited = set().union(*(fact_sources[entry[1]] for entry in selected))
                rows = [row for row in data['evidence'] if row['evidenceId'] in cited]
                supplied = [row['evidenceId'] for row in rows]
                if set(supplied) != cited:
                    return []
                refs = {row.get('tableDataRef') for row in rows}
                packet.update(requirements=[], evidence=rows,
                              tables={k: v for k, v in data['tables'].items() if k in refs})
                if scoped:
                    # Preserve order so /sourceFacts/INDEX/text still points
                    # to the same original value within the full proposal.
                    packet['proposal'] = {'sourceFacts': proposal['sourceFacts']}
                request, size = build_request(packet)
            else:
                if scoped and key == 'sectionChecks':
                    packet['requirements'] = []
                elif scoped:
                    packet['requirements'] = _requirements_for_checks(packet['requirements'], selected)
                # Preserve sources cited by the proposal as well as required
                # premises for the section and human-criteria reviews.
                request, size, supplied = fit_accounted_evidence(
                    record, packet, aliases, proposal, build_request, limit,
                    required_only=required_design_evidence_only)
            return {'request': request, 'inputBytes': size,
                    'checkIds': [entry[0] for entry in selected],
                    'suppliedEvidenceAliases': supplied}

        start = 0
        while start < len(checks):
            end = min(start + max_checks, len(checks))
            while end > start:
                part = build_part(checks[start:end])
                if part and part['inputBytes'] <= limit:
                    batches.append(part)
                    break
                if not fit_check_count:
                    return []
                end -= 1
            if end == start:
                return []
            start = end
    if pack_design_checks and scoped:
        packed = _pack_design_checks(record, data, aliases, proposal, build_request, limit, max_checks, batches)
        if packed:
            return packed
    return batches


def _pack_design_checks(record, data, aliases, proposal, build_request, limit, max_checks, batches):
    """Share the full design between one section group and one user requirement."""
    sections = data['sectionChecks']
    humans = data['humanChecks']
    if not (0 < len(sections) < max_checks and 1 < len(humans) <= max_checks):
        return None
    fact_ids = {entry[0] for entry in data['factChecks']}
    facts = [part for part in batches if set(part['checkIds']) <= fact_ids]
    if len(batches) <= len(facts) + 2:
        return None

    def packet(section_checks, human_checks):
        view = {**data, 'factChecks': [], 'sectionChecks': section_checks,
                'humanChecks': human_checks,
                'requirements': _requirements_for_checks(data['requirements'], human_checks)}
        request, size, supplied = fit_accounted_evidence(
            record, view, aliases, proposal, build_request, limit, required_only=True)
        return {'request': request, 'inputBytes': size,
                'checkIds': [entry[0] for entry in [*section_checks, *human_checks]],
                'suppliedEvidenceAliases': supplied}

    choices = []
    for index, human in enumerate(humans):
        shared = packet(sections, [human])
        if shared['inputBytes'] > limit:
            continue
        remainder = packet([], humans[:index] + humans[index + 1:])
        if remainder['inputBytes'] <= limit:
            choices.append([shared, remainder])
    if not choices:
        return None
    return [*facts, *min(choices, key=lambda pair: sum(part['inputBytes'] for part in pair))]
