"""Seal acceptance inputs and grading criteria before their first execution."""
import hashlib
import json


def case_definition_digest(manifest, case):
    payload = {
        'version': manifest['version'],
        'frozenAt': manifest['frozenAt'],
        'budgetProfile': manifest['budgetProfile'],
        'case': case,
        'materials': {key: value['sha256'] for key, value in manifest['materials'].items()},
        'review': manifest['review'],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def require_frozen_case(manifest, case):
    """Legacy manifests remain readable; sealed inputs must match exactly.

    Changing a question, expected finding, failure rule, source content hash,
    budget or grading criterion requires an explicitly new frozen definition.
    File locations are not grading inputs: moving an identical paper is safe.
    This local seal detects drift; it is not a signature or an acceptance score.
    """
    if 'caseDefinitionHashes' not in manifest:
        return
    seals = manifest['caseDefinitionHashes']
    if not isinstance(seals, dict):
        raise ValueError('Frozen case hashes are malformed; no request submitted.')
    expected = seals.get(case['id'])
    if (not isinstance(expected, str) or len(expected) != 64
            or any(c not in '0123456789abcdef' for c in expected)):
        raise ValueError('Frozen case hash is missing or invalid; no request submitted.')
    if case_definition_digest(manifest, case) != expected:
        raise ValueError('Frozen acceptance inputs or review criteria changed; freeze a new version before submitting.')
