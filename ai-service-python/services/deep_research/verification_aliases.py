"""Request-local evidence aliases; never rewrite quotations or claim identities."""
from copy import deepcopy


def encode_verification_inputs(claims, evidence):
    refs = {ref for claim in claims for ref in claim.get('evidenceRefs', [])}
    selected = [row for row in evidence if row['evidenceId'] in refs]
    identities = [row['evidenceId'] for row in selected]
    if len(identities) != len(set(identities)):
        raise ValueError('Duplicate evidence identity')
    occupied = refs | {row['evidenceId'] for row in evidence}
    prefix = 'E'
    while any(f'{prefix}{i + 1}' in occupied for i in range(len(selected))):
        prefix += '_'
    aliases = {identity: f'{prefix}{i + 1}' for i, identity in enumerate(identities)}
    reverse = {short: full for full, short in aliases.items()}
    wire_claims = deepcopy(claims)
    for claim in wire_claims:
        claim['evidenceRefs'] = [aliases.get(ref, ref) for ref in claim.get('evidenceRefs', [])]
        bindings = claim.get('tableBindings')
        for binding in bindings if isinstance(bindings, list) else []:
            if isinstance(binding, dict) and isinstance(binding.get('evidenceId'), str):
                binding['evidenceId'] = aliases.get(binding['evidenceId'], binding['evidenceId'])
    wire_evidence = deepcopy(selected)
    for row in wire_evidence:
        row['evidenceId'] = aliases[row['evidenceId']]
    return wire_claims, wire_evidence, reverse


def restore_visible_evidence(rows, reverse):
    restored = deepcopy(rows)
    for row in restored:
        row['evidenceId'] = reverse[row['evidenceId']]
    return restored


def restore_verdict_evidence(verdict, reverse, *, scope_expression=False):
    restored = deepcopy(verdict)
    if scope_expression:
        expression=restored.get('scopeExpressionAudit')
        for key in ('observedSettings','notEstablished'):
            rows=expression.get(key,[]) if isinstance(expression,dict) else []
            for item in rows if isinstance(rows,list) else []:
                premises=item.get('premises',[]) if isinstance(item,dict) else []
                for premise in premises if isinstance(premises,list) else []:
                    if isinstance(premise,dict) and isinstance(premise.get('evidenceId'),str):
                        premise['evidenceId']=reverse.get(premise['evidenceId'],premise['evidenceId'])
    purposes = restored.get('resultPurposeAudit')
    for row in purposes if isinstance(purposes, list) else []:
        if not isinstance(row, dict):
            continue
        for key in ('measurementPremise', 'purposePremise'):
            premise = row.get(key)
            if isinstance(premise, dict) and isinstance(premise.get('evidenceId'), str):
                premise['evidenceId'] = reverse.get(premise['evidenceId'], premise['evidenceId'])
    scope=restored.get('scopeAudit')
    for row in scope.get('premises',[]) if isinstance(scope,dict) and isinstance(scope.get('premises'),list) else []:
        if isinstance(row,dict) and isinstance(row.get('evidenceId'),str):
            row['evidenceId']=reverse.get(row['evidenceId'],row['evidenceId'])
    for key in ('dataAvailability', 'assetAvailability'):
        binding = restored.get(key)
        if isinstance(binding, dict) and isinstance(binding.get('evidenceId'), str):
            binding['evidenceId'] = reverse.get(binding['evidenceId'], binding['evidenceId'])
    audit=restored.get('comparisonAudit')
    if isinstance(audit,dict):
        rows=list(audit.get('premises',[])) if isinstance(audit.get('premises'),list) else []
        differences=audit.get('differences')
        for pair in differences if isinstance(differences,list) else []:
            if isinstance(pair,dict):
                rows.extend([pair.get('left'),pair.get('right')])
        for row in rows:
            if isinstance(row,dict) and isinstance(row.get('evidenceId'),str):
                row['evidenceId']=reverse.get(row['evidenceId'],row['evidenceId'])
    return restored


def restore_coverage_evidence(verdicts, reverse):
    """Restore only typed source IDs; never rewrite excerpts or claim IDs."""
    restored = deepcopy(verdicts)
    for verdict in restored:
        if not isinstance(verdict, dict):
            continue
        aspects = verdict.get('aspects')
        for aspect in aspects if isinstance(aspects, list) else []:
            basis = aspect.get('basis') if isinstance(aspect, dict) else None
            if (isinstance(basis, dict) and basis.get('kind') in {'source', 'source_metadata'}
                    and isinstance(basis.get('evidenceId'), str)):
                basis['evidenceId'] = reverse.get(basis['evidenceId'], basis['evidenceId'])
    return restored
