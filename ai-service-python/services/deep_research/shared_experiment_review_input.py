"""Fit complete proposals and frozen evidence obligations to a review window."""


def fit_accounted_evidence(record, data, aliases, proposal, build_request, limit, *, feedback_refs=()):
    rows = data['evidence']

    def build(selected):
        packet_ids = {row.get('tableDataRef') for row in selected}
        scoped = {**data, 'evidence':selected, 'tables':{key:value for key,value in data['tables'].items()
                                                     if key in packet_ids}}
        request, size = build_request(scoped)
        return request, size, [row['evidenceId'] for row in selected]

    request, size = build_request(data)
    supplied = [row['evidenceId'] for row in rows]
    if size <= limit:
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
    if compact[1] > limit:
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


def partition_bounded_review(record, data, aliases, proposal, build_request, limit, max_checks, *, scoped=False):
    """Keep the full design in design reviews; facts may use their own source packet."""
    fact_sources = {fact['id']: set(fact['evidenceRefs']) for fact in proposal['sourceFacts']}
    batches = []
    for key in ('factChecks', 'sectionChecks', 'humanChecks'):
        checks = data[key]
        for start in range(0, len(checks), max_checks):
            selected = checks[start:start + max_checks]
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
                    wanted = {(oid, cid) for _, oid, cid in selected}
                    requirements = []
                    for row in packet['requirements']:
                        oid = row['obligationId']
                        if (oid, 'whole') in wanted:
                            requirements.append(row)
                            continue
                        criteria = [c for c in row.get('completionCriteria', [])
                                    if (oid, c['criterionId']) in wanted]
                        if criteria:
                            requirements.append({**row, 'completionCriteria': criteria})
                    packet['requirements'] = requirements
                # Preserve sources cited by the proposal as well as required
                # premises for the section and human-criteria reviews.
                request, size, supplied = fit_accounted_evidence(
                    record, packet, aliases, proposal, build_request, limit)
            if size > limit:
                return []
            batches.append({'request': request, 'inputBytes': size,
                            'checkIds': [entry[0] for entry in selected],
                            'suppliedEvidenceAliases': supplied})
    return batches
