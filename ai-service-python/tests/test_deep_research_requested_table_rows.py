from unittest.mock import Mock

import pytest

from services.deep_research.contracts import BudgetExhaustedError
from services.deep_research.extraction import make_batched_extract_node
from services.deep_research.requested_table_rows import requested_table_row_spans
from services.deep_research.verification import make_evidence, verify_claims
from test_deep_research_extraction import setup


TEXT = ('Paper: Example\nTable caption: Results on Dataset Small, individual scenes.\n'
        'Table row 1: Scene | PSNR\nTable row 2: Boat | 12\nTable row 3: Cabin | 14\n')


def test_requested_unit_retains_exact_caption_and_row_without_guessing_columns():
    spans = requested_table_row_spans(TEXT, '只在boat场景设计一个实验')
    assert len(spans) == 1 and spans[0] in TEXT
    assert spans[0].startswith('Table caption: Results on Dataset Small')
    assert spans[0].endswith('Table row 2: Boat | 12')
    assert 'Cabin' not in spans[0]
    assert requested_table_row_spans(TEXT, 'Use boathouse instead.') == []
    assert requested_table_row_spans(TEXT.replace('Table caption:', 'Unlabelled context:'), 'Boat') == []
    assert requested_table_row_spans(TEXT, 'Boat', max_chars=10) == []


def test_named_unit_context_survives_extraction_budget_stop_without_numeric_approval(tmp_path):
    repo, reads = setup(tmp_path)
    reads[0].update(location={'page': 5, 'tableColumnMappingUnverified': True},
                    pages=[{'text': TEXT}], tableData=None)
    repo.update_run('r', lambda r: {**r, 'question': 'Design an experiment on Boat.',
                                   'state': {**r['state'], 'readResults': [reads[0]]}})
    invoke = Mock(side_effect=BudgetExhaustedError('modelCalls', 13, 13))
    with pytest.raises(BudgetExhaustedError):
        make_batched_extract_node(invoke, make_evidence, lambda *a: True, repo.update_run)({'run_id': 'r'})
    evidence = repo.require_run('r')['state']['evidence']
    assert len(evidence) == 1
    ev = evidence[0]
    assert ev['sourceWorkId'] == 'p0' and ev['sourceVersionId'] == 'v0' and ev['location']['page'] == 5
    assert ev['quote'] in TEXT and ev['verification']['semantic'] == 'unchecked'
    assert ev.get('tableData') is None
    checked = verify_claims([{'claimId': 'c', 'kind': 'reported', 'text': 'Boat achieved PSNR 12.',
                              'evidenceRefs': [ev['evidenceId']]}], evidence,
                            lambda *a: [{'claimId': 'c', 'status': 'passed'}])
    assert not checked['accepted']  # Literal membership retention does not certify numerical columns.


def test_revoked_or_abstract_named_row_never_gains_literal_fulltext_evidence(tmp_path):
    repo, reads = setup(tmp_path)
    reads[0].update(pages=[{'text': TEXT}], accessLevel='abstract')
    reads[1].update(pages=[{'text': TEXT}], accessLevel='fulltext')
    repo.update_run('r', lambda r: {**r, 'question': 'Boat',
                                   'state': {**r['state'], 'readResults': reads[:2]}})
    make_batched_extract_node(Mock(return_value={'content': '[]'}), make_evidence,
        lambda _, pid: pid != 'p1', repo.update_run)({'run_id': 'r'})
    assert repo.require_run('r')['state']['evidence'] == []
