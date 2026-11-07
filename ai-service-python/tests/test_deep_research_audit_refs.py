from copy import deepcopy
import pytest

from services.deep_research.design_audit import validate_design_audit


def claim():
    return {'claimId': 'data', 'kind': 'proposal', 'designRole': 'data',
        'executionSpec': {'dataset': 'D', 'scenes': {'mode': 'named', 'names': ['scene-a']},
            'split': {'mode': 'seeded_fraction', 'evaluationFraction': .2, 'seed': 7},
            'seeds': [42], 'independentUnit': 'scene', 'replication': {'mode': 'fixed_checkpoint'}}}


def audit():
    return {'designAudit': {slot: {'ref': {'claimId': 'data', 'path': ['executionSpec', root]}}
        for slot, root in {'scenes': 'scenes', 'split': 'split', 'seeds': 'seeds', 'sampling_unit': 'independentUnit'}.items()}}


def test_exact_typed_refs_resolve_existing_values_without_approving_scientific_validity_or_mutation():
    c, verdict = claim(), audit()
    before = deepcopy((c, verdict))
    assert validate_design_audit(c, verdict, []) == []
    assert (c, verdict) == before
    for ref in [
        {'claimId': 'missing', 'path': ['executionSpec', 'independentUnit']},
        {'claimId': 'data', 'path': ['executionSpec', 'dataset']},
        {'claimId': 'data', 'path': ['text']},
        {'claimId': 'data', 'path': ['executionSpec', 'seeds', True]},
        {'claimId': 'data', 'path': ['executionSpec', 'independentUnit'], 'value': 'guessed'}]:
        bad = deepcopy(verdict)
        bad['designAudit']['sampling_unit'] = {'ref': ref}
        assert 'sampling_unit' in validate_design_audit(c, bad, [])


@pytest.mark.parametrize('version', [None, True, 0, 99])
def test_step_fields_cannot_bind_an_unversioned_or_unsupported_workflow(version):
    c = {'claimId': 'steps', 'kind': 'proposal', 'designRole': 'steps',
         'text': 'An older prose-only protocol.', 'executionSpec': {'records': ['invented']}}
    if version is not None:
        c['workflowContractVersion'] = version
    verdict = {'designAudit': {'saved_artifacts': {'ref': {
        'claimId': 'steps', 'path': ['executionSpec', 'records']}}}}
    assert 'saved_artifacts' in validate_design_audit(c, verdict, [])
