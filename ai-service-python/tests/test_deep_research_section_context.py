from copy import deepcopy
from types import SimpleNamespace
import pytest

from services.deep_research.section_context import include_section_context


def row(i, text, page=5):
    return {'sourceId': f'p-v{"a" * 16}-chunk-{i}', 'pdfId': 'p',
            'sourceType': 'current_paper', 'text': text,
            'metadata': {'id': 'p', 'index_version': 'a' * 16, 'section_title': 'TRAINING', 'chunk_index': i},
            'location': {'page': page, 'chunk': i, 'section': 'TRAINING'}}


def record():
    return {'localSectionContextContractVersion': 1, 'sectionPremisesContractVersion': 2,
            'question': '解释第5节中两个约束分别约束什么。',
            'state': {'outputKind': 'claim_verification'}}


def sample():
    head = row(34, '5 TRAINING\nTwo regularizers are introduced. Depth distortion concentrates the weight')
    next1 = row(35, 'distribution along the ray. Normal consistency aligns splats')
    next2 = row(36, 'with normals computed from depth gradients.')
    return [head, row(50, 'Ablation result.'), row(51, 'Another experiment.')], [head, next1, next2]


def test_requested_section_gets_separate_unchanged_successors_within_limit():
    selected, candidates = sample();before = deepcopy((selected, candidates))
    out = include_section_context(selected, candidates, record(), 'p', 3)
    assert [r['location']['chunk'] for r in out] == [34, 35, 36]
    assert out[0] is selected[0]
    for original, result in zip(candidates[1:], out[1:]):
        assert {k: result[k] for k in original} == original
        assert result['contextForSourceId'] == selected[0]['sourceId']
    assert (selected, candidates) == before


@pytest.mark.parametrize('change', [
    {'pdfId': 'foreign'}, {'accessLevel': 'abstract'}, {'sourceId': 'forged'},
    {'location': {'page': 9, 'chunk': 35, 'section': 'TRAINING'}},
    {'metadata': {'id': 'foreign'}}, {'metadata': {'index_version': 'b' * 16}},
    {'metadata': {'section_title': 'RESULTS'}}, {'metadata': {'chunk_index': True}},
])
def test_invalid_next_chunk_cannot_bridge_to_a_later_one(change):
    selected, candidates = sample()
    for k, value in change.items():
        if k == 'metadata': candidates[1][k].update(value)
        else: candidates[1][k] = value
    assert include_section_context(selected, candidates, record(), 'p', 3) == selected


def test_ambiguous_successor_and_old_or_non_explanation_runs_keep_old_selection():
    selected, candidates = sample()
    assert include_section_context(selected, candidates + [candidates[1]], record(), 'p', 3) == selected
    for marker in [None, False, True, 0, 3]:
        r = record();r['localSectionContextContractVersion'] = marker
        assert include_section_context(selected, candidates, r, 'p', 3) == selected
    for question in ['解释方法。', '不要解释第5节。', '比较第5节中的性能。']:
        r = record();r['question'] = question
        assert include_section_context(selected, candidates, r, 'p', 3) == selected


def test_no_source_limit_increase_or_loss_of_best_hit_and_existing_context_pairs():
    selected, candidates = sample();best = row(0, 'Best semantic hit.')
    out = include_section_context([best] + selected, candidates, record(), 'p', 4)
    assert out[0] is best and len(out) == 4
    assert include_section_context([best] + selected, candidates, record(), 'p', 3) == [best] + selected[:2]
    selected[1]['contextForSourceId'] = selected[2]['sourceId']
    assert include_section_context(selected, candidates, record(), 'p', 3) == selected


def test_local_retriever_applies_selector_and_rejects_revoked_scope():
    from services.deep_research.local_sources import LocalTaskRetriever
    from services.deep_research.contracts import DeepResearchError
    selected, candidates = sample();r = record();r['scopeEvidenceContractVersion'] = 1
    reader = LocalTaskRetriever(SimpleNamespace(require_run=lambda _: r), 'run', lambda *_: True, origin='http://localhost')
    assert [x['location']['chunk'] for x in reader._scope_evidence(selected, candidates, '', 'p', 3)] == [34, 35, 36]
    reader.validate = lambda *_: False
    with pytest.raises(DeepResearchError, match='论文范围'):
        reader._scope_evidence(selected, candidates, '', 'p', 3)


def test_new_activation_is_server_owned_and_immutable(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3');repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        r, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'one', 'question': 'Explain',
            'deferStart': True, 'localSectionContextContractVersion': 0}, start_async=False)
        assert r['localSectionContextContractVersion'] == 2
        for value in [None, True, 0, 3]:
            with pytest.raises(ValueError, match='Immutable run field'):
                repo.update_run(r['runId'], lambda x: {**x, 'localSectionContextContractVersion': value})
    finally:
        facade.shutdown()
