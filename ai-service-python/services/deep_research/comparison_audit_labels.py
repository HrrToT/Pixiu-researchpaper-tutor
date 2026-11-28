"""Short wire labels for fixed answer checks. Domain identities stay unchanged."""
from collections.abc import Mapping
from itertools import count


def labels(requirements):
    check_numbers = count(1)
    return {row['obligationId']: (f'R{index}', {
        check['checkId']: f'K{next(check_numbers)}' for check in row['checks']
    }) for index, row in enumerate(requirements, 1)}


def project(data, key_map):
    """Replace identifiers on the renderer's private copy and show the expected rows."""
    catalog = data.get('bindingCatalog') or {}
    for row in [*data['requirements'], *catalog.get('obligations', [])]:
        row['obligationId'], checks = key_map[row['obligationId']]
        for check in row['checks']:
            check['checkId'] = checks[check['checkId']]
    for claim in data['claims']:
        if 'obligationIds' in claim:
            claim['obligationIds'] = [key_map[key][0] if key in key_map else key for key in claim['obligationIds']]
    return [[row, list(checks.values())] for row, checks in key_map.values()]


def limit_ids(requirements):
    return {(row['obligationId'], check['checkId']) for row in requirements for check in row['checks']
            if check.get('responseType') == 'limitation'}


def _restore_limit_bindings(check):
    """Expand exactly the model's quotations into the existing literal evidence validator."""
    if 'limitSpans' in check or not isinstance(check.get('bindings'), list):
        return None
    bindings, spans = [], []
    missing_excerpt_field = False
    for binding in check['bindings']:
        if not isinstance(binding, dict) or set(binding) not in ({'claimId', 'field'}, {'claimId', 'field', 'excerpt'}):
            return None
        missing_excerpt_field = missing_excerpt_field or 'excerpt' not in binding
        excerpt = binding.get('excerpt')
        if excerpt is not None and not isinstance(excerpt, str):
            return None
        anchor = {key: binding[key] for key in ('claimId', 'field')}
        if anchor not in bindings:
            bindings.append(anchor)
        if excerpt is not None:
            spans.append({**anchor, 'excerpt': excerpt})
    # The normalizer still diagnoses an old-format positive response as
    # unanchored. A deliberate null is an explicit absence of a quotation.
    return {**check, 'bindings': bindings,
            **({'limitSpans': spans} if not missing_excerpt_field else {})}


def restore(value, key_map, *, inline_limits=frozenset()):
    """Restore only supplied IDs. Never complete missing rows or guess a review."""
    if not isinstance(value, list):
        return None
    reverse = {alias: (key, {value: name for name, value in checks.items()})
               for key, (alias, checks) in key_map.items()}
    result = []
    for row in value:
        alias = row.get('obligationId') if isinstance(row, Mapping) else None
        if not isinstance(alias, str) or alias not in reverse:
            return None
        obligation, checks = reverse[alias]
        restored = {**row, 'obligationId': obligation}
        if isinstance(row.get('checks'), list):
            restored_checks = []
            for check in row['checks']:
                code = check.get('checkId') if isinstance(check, Mapping) else None
                if not isinstance(code, str) or code not in checks:
                    return None
                check_id = checks[code]
                restored_check = {**check, 'checkId': check_id}
                if (obligation, check_id) in inline_limits:
                    restored_check = _restore_limit_bindings(restored_check)
                    if restored_check is None:
                        return None
                restored_checks.append(restored_check)
            restored['checks'] = restored_checks
        result.append(restored)
    return result
