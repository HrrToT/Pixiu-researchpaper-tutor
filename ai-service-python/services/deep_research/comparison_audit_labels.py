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


def restore(value, key_map):
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
                restored_checks.append({**check, 'checkId': checks[code]})
            restored['checks'] = restored_checks
        result.append(restored)
    return result
