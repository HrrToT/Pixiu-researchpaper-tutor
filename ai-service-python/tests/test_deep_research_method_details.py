from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.method_details import include_method_details


def passage(index, body, *, owner='p', version='a'*16, section='Method'):
    return {'sourceId': f'{owner}-{version}-{index}', 'pdfId': owner,
        'text': 'Paper: TMC Everywhere\nSection: '+section+'\nContent:\n'+body,
        'location': {'page': 4, 'chunk': index, 'section': section},
        'metadata': {'id': owner, 'index_version': version, 'chunk_index': index, 'section_title': section}}


def example():
    top = passage(0, 'We train TMC using the previous representation.')
    generic = [passage(i, 'General overview without component parameters.') for i in range(1,5)]
    previous = passage(11, 'TMC encodes the previous sample position.')
    details = passage(12, 'This maps the TMC encoding to seven output dimensions: translation and rotation.')
    return [top, *generic], previous, details


def test_literal_component_operation_replaces_generic_hits_with_separate_exact_context_sources():
    indexed, previous, details = example()
    decoy = passage(20, 'Another network outputs every attribute including colour and opacity.')
    before = deepcopy([indexed, previous, details, decoy])
    found = include_method_details(indexed, [*indexed, decoy, previous, details],
                                   'TMC prediction parameters previous frame', 'p', 5)
    assert [row['metadata']['chunk_index'] for row in found] == [0,11,12,1,2]
    assert found[1]['text'] == previous['text'] and found[2]['text'] == details['text']
    assert found[1]['contextForSourceId'] == details['sourceId']
    assert found[2]['retrievalMode'] == 'indexed_method_detail'
    assert len({row['sourceId'] for row in found}) == 5
    assert [indexed, previous, details, decoy] == before


@pytest.mark.parametrize('changed', ['foreign', 'other-version', 'duplicate-index', 'different-section', 'missing-predecessor'])
def test_ambiguous_or_foreign_context_never_enters_the_query_result(changed):
    indexed, previous, details = example()
    candidates = [previous, details]
    if changed == 'foreign':
        candidates = [passage(11, 'TMC inputs', owner='foreign'), details]
    elif changed == 'other-version':
        candidates = [passage(11, 'TMC inputs', version='b'*16), details]
    elif changed == 'duplicate-index':
        candidates.append(passage(11, 'Conflicting TMC inputs', section='Other'))
    elif changed == 'different-section':
        candidates = [passage(11, 'TMC inputs', section='Another method'), details]
    else:
        candidates = [details]
    assert include_method_details(indexed, candidates, 'TMC prediction parameters', 'p', 5) == indexed


def test_small_envelope_existing_context_and_already_retrieved_details_are_preserved():
    indexed, previous, details = example()
    assert include_method_details(indexed[:2], [previous,details], 'TMC prediction', 'p', 2) == indexed[:2]
    existing = [{**indexed[0], 'contextForSourceId': indexed[1]['sourceId']}, indexed[1], indexed[2]]
    assert include_method_details(existing, [previous,details], 'TMC prediction', 'p', 3) == existing
    ready = [indexed[0], previous, details]
    assert include_method_details(ready, [previous,details], 'TMC prediction', 'p', 3) == ready


def test_no_detail_expansion_for_unrelated_queries_or_unpinned_index():
    indexed, previous, details = example()
    assert include_method_details(indexed,[previous,details],'report benchmark FPS','p',5) == indexed
    indexed[0]['metadata'].pop('index_version')
    assert include_method_details(indexed,[previous,details],'TMC prediction','p',5) == indexed


def test_non_acronym_queries_require_multiple_body_terms_and_operation_language():
    indexed, _, _ = example()
    detail = passage(30, 'Deformation encoding predicts position offsets from time inputs.')
    found = include_method_details(indexed, [detail], 'deformation encoding input parameters', 'p', 5)
    assert found[1]['sourceId'] == detail['sourceId']
    assert found[1]['text'] == detail['text']
    assert include_method_details(indexed, [detail], 'unrelated deformation output', 'p', 5) == indexed


@pytest.mark.parametrize('replacement', [0, True, 1, 2, '3', None])
def test_precision_contract_is_server_owned_and_immutable(tmp_path, replacement):
    repo = DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_:None, llm_client=object())
    try:
        run,_ = facade.create({'workspaceTaskId':'t','operationKey':'op','question':'解释机制',
            'sourcePrecisionContractVersion':replacement,'deferStart':True},start_async=False)
        assert run['sourcePrecisionContractVersion'] == 3
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'sourcePrecisionContractVersion':replacement})
    finally:
        facade.shutdown()
