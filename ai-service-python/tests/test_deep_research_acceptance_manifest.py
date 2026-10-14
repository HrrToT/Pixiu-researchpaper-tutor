from copy import deepcopy

import pytest

from services.deep_research.acceptance_manifest import case_definition_digest, require_frozen_case
from scripts.verify_deep_research_case import run_case


def frozen_manifest():
    manifest = {
        'version': 1, 'frozenAt': '2026-10-14', 'budgetProfile': 'standard',
        'materials': {'paper': {'sha256': 'a' * 64, 'path': 'original.pdf'}},
        'review': {'minimumScore': 4, 'hardFailures': ['fabrication']},
        'cases': [{'id': 'H1R', 'split': 'holdout', 'kind': 'claim_verification',
                   'policy': 'task_only', 'materials': ['paper'], 'question': '解释方法',
                   'required': ['camera alignment'], 'forbidden': ['no cameras']}],
    }
    case = manifest['cases'][0]
    manifest['caseDefinitionHashes'] = {case['id']: case_definition_digest(manifest, case)}
    return manifest


@pytest.mark.parametrize('field,value', [
    ('question', 'different question'), ('required', ['changed criterion']),
    ('forbidden', []), ('split', 'development'), ('policy', 'academic_external'),
])
def test_case_changes_are_rejected_before_network_or_receipt(tmp_path, field, value):
    manifest = frozen_manifest()
    manifest['cases'][0][field] = value
    calls = []
    with pytest.raises(ValueError, match='changed'):
        run_case(manifest, 'H1R', 1, tmp_path, lambda *a, **k: calls.append(a),
                 submit=True, check_ready=lambda: calls.append('health'))
    assert not calls and not list(tmp_path.iterdir())


@pytest.mark.parametrize('change', ['budget', 'review', 'source', 'version', 'date'])
def test_shared_acceptance_inputs_are_sealed(change):
    manifest = frozen_manifest()
    if change == 'budget':
        manifest['budgetProfile'] = 'large'
    elif change == 'review':
        manifest['review']['minimumScore'] = 3
    elif change == 'source':
        manifest['materials']['paper']['sha256'] = 'b' * 64
    elif change == 'version':
        manifest['version'] = 2
    else:
        manifest['frozenAt'] = '2026-10-15'
    with pytest.raises(ValueError, match='changed'):
        require_frozen_case(manifest, manifest['cases'][0])


@pytest.mark.parametrize('seals', [None, [], {}, {'H1R': 'abc'}, {'H1R': 'A' * 64}])
def test_missing_or_malformed_seal_is_rejected(seals):
    manifest = frozen_manifest()
    manifest['caseDefinitionHashes'] = seals
    with pytest.raises(ValueError):
        require_frozen_case(manifest, manifest['cases'][0])


def test_identical_source_relocation_and_key_order_are_safe():
    manifest = frozen_manifest()
    relocated = deepcopy(manifest)
    relocated['materials']['paper']['path'] = 'another/location.pdf'
    relocated['review'] = dict(reversed(list(relocated['review'].items())))
    require_frozen_case(relocated, relocated['cases'][0])


def test_legacy_manifest_remains_readable():
    manifest = frozen_manifest()
    del manifest['caseDefinitionHashes']
    require_frozen_case(manifest, manifest['cases'][0])


def test_valid_sealed_preview_stays_offline(tmp_path):
    manifest = frozen_manifest()
    def forbidden(*args, **kwargs):
        raise AssertionError('Preview must be offline')
    assert run_case(manifest, 'H1R', 1, tmp_path, forbidden, check_ready=forbidden)['preview']
    assert not list(tmp_path.iterdir())
