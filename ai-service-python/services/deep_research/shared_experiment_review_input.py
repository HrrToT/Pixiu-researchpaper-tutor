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
