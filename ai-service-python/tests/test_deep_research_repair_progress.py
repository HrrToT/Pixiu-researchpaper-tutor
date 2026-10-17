from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.facade import ResearchFacade
from services.deep_research.graph import make_verify_node
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.repair_progress import partition_revisions


def inputs(kind='reported'):
    original = {'claimId': 'c', 'kind': kind, 'text': 'The cache also predicts scale.',
                'evidenceRefs': ['a', 'b'], 'conditions': {}, 'detailLevel': 'fulltext'}
    verification = {'accepted': [], 'rejected': [{'claimId': 'c', 'reason': 'semantic_unresolved',
        'detail': 'The cited passages establish only translation and rotation.'}]}
    return original, verification


@pytest.mark.parametrize('kind', ['reported', 'inference'])
def test_reordering_citations_whitespace_or_binding_order_does_not_repair_a_rejected_fact(kind):
    original, initial = inputs(kind)
    original['tableBindings'] = [{'value': '1'}, {'value': '2'}]
    revised = {**original, 'text': '  The cache also\n predicts scale. ',
               'evidenceRefs': ['b', 'a'], 'tableBindings': list(reversed(original['tableBindings']))}
    before = deepcopy([original, initial, revised])
    eligible, rejected = partition_revisions({'claims': [original]}, initial, [revised])
    assert not eligible and rejected[0]['reason'] == 'unchanged_semantic_rejection'
    assert rejected[0]['detail'] == initial['rejected'][0]['detail']
    assert [original, initial, revised] == before


@pytest.mark.parametrize('change', [
    {'text': 'The cache predicts translation and rotation.'},
    {'evidenceRefs': ['a', 'new-passage']},
    {'conditions': {'scope': 'Only the documented baseline variant.'}},
    {'tableBindings': [{'value': 'corrected-cell'}]},
    {'detailLevel': 'abstract'},
])
def test_changed_basis_or_narrowed_wording_still_requires_all_independent_checks(change):
    original, initial = inputs()
    revised = {**original, **change}
    eligible, rejected = partition_revisions({'claims': [original]}, initial, [revised])
    assert eligible == [revised] and not rejected  # Eligibility is not acceptance.


def test_proposals_and_hard_binding_repairs_are_not_blocked_as_unchanged_facts():
    original, initial = inputs('proposal')
    assert partition_revisions({'claims': [original]}, initial, [original]) == ([original], [])
    original, initial = inputs()
    initial['rejected'][0]['reason'] = 'table_binding_mismatch'
    assert partition_revisions({'claims': [original]}, initial, [original]) == ([original], [])


@pytest.mark.parametrize('marked', [True, False])
def test_saved_graph_draft_cannot_reshuffle_a_verdict_or_resend_on_reopen(marked):
    original, initial = inputs()
    revised = {**original, 'evidenceRefs': ['b', 'a']}
    record = {**({'repairProgressContractVersion': 1} if marked else {}), 'state': {
        'reportBody': {'claims': [original]}, 'evidence': [], 'repairAttempted': True,
        'initialVerification': initial, 'initialAnswerCoverage': {'status': 'not_requested', 'gaps': []},
        'repairReport': {'claims': [original]}, 'repairTargets': initial, 'repairDraft': [revised]}}
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    verifier = Mock(return_value={'accepted': [revised], 'rejected': []})
    invoke = Mock()
    node = make_verify_node(verifier, None, update, llm_invoke=invoke)
    node({'run_id': 'r'})
    if marked:
        verifier.assert_not_called()
        assert not record['state']['verifiedReport']['verifiedClaims']
        assert record['state']['repairUnchangedRejections'][0]['originalReason'] == 'semantic_unresolved'
    else:
        verifier.assert_called_once()
        assert record['state']['verifiedReport']['verifiedClaims'] == [revised]
    invoke.assert_not_called()
    previous = verifier.call_count
    node({'run_id': 'r'})
    assert verifier.call_count == previous
    invoke.assert_not_called()


@pytest.mark.parametrize('replacement', [0, True, '1', None])
def test_repair_progress_contract_is_owned_and_frozen_by_the_server(tmp_path, replacement):
    repo = DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        run, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'op', 'question': '核查主张',
            'deferStart': True, 'repairProgressContractVersion': replacement}, start_async=False)
        assert run['repairProgressContractVersion'] == 1
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(run['runId'], lambda r: {**r, 'repairProgressContractVersion': replacement})
    finally:
        facade.shutdown()
