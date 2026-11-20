"""Discovery routing cannot discard relevant evidence from an allowed paper."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.extraction import make_batched_extract_node
from services.deep_research.graph import make_extract_node
from services.deep_research.obligation_binding import eligible_obligation_ids
from services.deep_research.verification import make_evidence


def inputs(required=None):
    source = {'sourceId': 's', 'workId': 'paper-A', 'versionId': 'version-A', 'ownerMaterialId': 'owner-A',
              'contentHash': 'hash', 'accessLevel': 'fulltext', 'obligationIds': ['motivation'],
              'pages': [{'page': 5, 'text': 'The opacity carries the loss gradient to the probabilities during training.'}]}
    obligations = [
        {'obligationId': 'motivation', 'question': 'Why choose this representation?', 'requiredSources': []},
        {'obligationId': 'training', 'question': 'How does the loss update the probabilities?', 'requiredSources': required or []}]
    return source, obligations


@pytest.mark.parametrize('required', [[], ['paper-A'], ['version-A'], ['owner-A'], ['paper-A', 'paper-B']])
def test_exact_allowed_work_version_or_owner_can_inform_another_question(required):
    source, obligations = inputs(required)
    before = deepcopy((source, obligations))
    assert eligible_obligation_ids(source, {o['obligationId']: o for o in obligations}) == ['motivation', 'training']
    assert (source, obligations) == before


@pytest.mark.parametrize('required', [['paper-B'], ['version-B'], ['s'], ['PAPER-A']])
def test_other_paper_and_query_id_do_not_establish_required_source(required):
    source, obligations = inputs(required)
    assert eligible_obligation_ids(source, {o['obligationId']: o for o in obligations}) == ['motivation']


@pytest.mark.parametrize('batch', [False, True])
def test_cross_question_quote_is_retained_without_changing_document_identity(batch):
    source, obligations = inputs()
    record = {'state': {'readResults': [source], 'plan': [{'obligations': obligations}]}}
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    invoke = Mock(return_value={'content': json.dumps([{'sourceId': 's', 'quote': source['pages'][0]['text'],
        'obligationIds': ['training', 'unknown'], 'conditions': {}}])})
    factory = make_batched_extract_node if batch else make_extract_node
    factory(invoke, make_evidence, lambda *args: True, update)({'run_id': 'r'})
    evidence = record['state']['evidence']
    assert len(evidence) == 1 and evidence[0]['obligationIds'] == ['training']
    assert evidence[0]['quote'] == source['pages'][0]['text']
    assert (evidence[0]['sourceWorkId'], evidence[0]['sourceVersionId'], evidence[0]['contentHash']) == ('paper-A','version-A','hash')
    assert evidence[0]['verification'] == {'literal': 'passed', 'semantic': 'unchecked'}


@pytest.mark.parametrize('batch', [False, True])
def test_foreign_required_paper_still_cannot_gain_a_cross_question_quote(batch):
    source, obligations = inputs(['paper-B'])
    record = {'state': {'readResults': [source], 'plan': [{'obligations': obligations}]}}
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    invoke = Mock(return_value={'content': json.dumps([{'sourceId': 's', 'quote': source['pages'][0]['text'],
        'obligationIds': ['training'], 'conditions': {}}])})
    factory = make_batched_extract_node if batch else make_extract_node
    factory(invoke, make_evidence, lambda *args: True, update)({'run_id': 'r'})
    assert not record['state']['evidence']
    if batch:
        passages = json.loads(invoke.call_args.args[2].split('Passages:\n')[1])
        assert [o['obligationId'] for o in passages[0]['obligations']] == ['motivation']


def test_reused_quote_rebinds_only_eligible_questions_and_never_inherits_relevance():
    source, obligations = inputs(['paper-B'])
    evidence = make_evidence({'workId': 'paper-A', 'versionId': 'version-A', 'contentHash': 'hash', 'accessLevel': 'fulltext'},
        source['pages'][0]['text'], source['pages'][0]['text'], location={'page': 5}, obligation_ids=['old'])
    evidence.update(sourceId='s')
    record = {'state': {'readResults': [source], 'evidence': [evidence], 'plan': [{'obligations': obligations}]}}
    def update(run, change, **kwargs):
        nonlocal record
        record = change(record)
        return record
    invoke = Mock()
    make_batched_extract_node(invoke, make_evidence, lambda *args: True, update)({'run_id': 'r'})
    invoke.assert_not_called()
    assert record['state']['evidence'][0]['obligationIds'] == ['motivation']
    assert record['state']['evidence'][0]['verification']['semantic'] == 'unchecked'
