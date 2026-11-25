import pytest

from services.deep_research.bound_composite_table_cells import all_composite_series_bound
from services.deep_research.table_bindings import _method_visible
from services.deep_research.verification import make_evidence, verify_claims


METHOD = 'GPT-3 175B (Fine-Tune)'
DATASET = 'SAMSum'
METRIC = 'R1/R2/RL'
VALUE = '52.0/28.0/44.5'
CELL = (('version-v1', 3, 2), DATASET, METHOD, METRIC, VALUE)
DISPLAY = f'{METHOD} 在 {DATASET} 的 {METRIC} 为 {VALUE}。'


def validate(fields, cells=(CELL,)):
    return all_composite_series_bound(fields, cells, _method_visible)


def test_complete_metric_vector_bound_to_its_own_explicit_display():
    assert validate([DISPLAY])
    assert validate([DISPLAY.replace('/', ' ／ ')])
    assert validate([DISPLAY.replace('为', ':')])
    assert validate([f'On {DATASET} the {METHOD} {METRIC} is {VALUE}.'])


@pytest.mark.parametrize('display', [
    DISPLAY.replace(METRIC, 'score'), DISPLAY.replace(DATASET, 'another dataset'),
    DISPLAY.replace(METHOD, 'other method'), DISPLAY.replace(VALUE,'52.0/44.5/28.0'),
    DISPLAY.replace(VALUE,'52.0/28.0/44.5/123.4'), DISPLAY + 'Other results are 45.0/39.0.',
    DISPLAY.replace(' 的 ', '。'), DISPLAY.replace(VALUE, '52.0/-28.0/44.5'),
    'Unnamed: 52/-28.', 'P2/4 is not a metric display.', DISPLAY.replace(VALUE, VALUE+'%'),
    DISPLAY.replace(DATASET, DATASET + '-heldout'),
    DISPLAY.replace(VALUE, VALUE + '/unknown'),
])
def test_malformed_misassigned_and_additional_slash_series_fail_closed(display):
    assert not validate([display])


def test_role_display_does_not_borrow_labels_across_fields_or_identical_cited_versions():
    assert not validate([f'{METHOD} 在 {DATASET}。', f'{METRIC}: {VALUE}'])
    assert not validate([DISPLAY],(CELL,(('version-v2', 3, 2),*CELL[1:])))


def evidence_and_claim():
    quote = f'Table row 3: {METHOD} | {VALUE}'
    evidence = make_evidence(
        {'workId': 'paper', 'versionId': 'v1', 'contentHash': 'hash', 'accessLevel': 'fulltext'},
        quote, quote, location={'page': 6, 'table': 't1'}, obligation_ids=[],
    )
    evidence['tableData'] = {'groups': [[DATASET, [METRIC]]], 'rows': [[3, METHOD, [VALUE]]]}
    reference = evidence['evidenceId']
    claim = {
        'claimId': 'c', 'kind': 'reported', 'text': DISPLAY, 'evidenceRefs': [reference],
        'tableBindings': [{'evidenceId': reference, 'rowNumber': 3, 'groupIndex': 0,
                           'metric': METRIC, 'value': VALUE}],
    }
    return evidence, claim


def test_bound_display_requires_policy_and_independent_semantic_approval():
    evidence, claim = evidence_and_claim()
    def passed(claims, sources):
        assert claims[0]['claimId'] == 'c'
        assert sources[0]['evidenceId'] == evidence['evidenceId']
        return [{'claimId': 'c', 'status': 'passed'}]

    old = verify_claims([claim], [evidence], passed)
    assert old['rejected'][0]['reason'] == 'ambiguous_table_series'
    assert verify_claims([claim], [evidence], passed, bound_composite_cells=True)['accepted']
    assert not verify_claims([claim], [evidence], bound_composite_cells=True)['accepted']


def test_cited_table_without_exact_binding_cannot_support_series():
    evidence, claim = evidence_and_claim()
    del claim['tableBindings']
    report = verify_claims([claim], [evidence], bound_composite_cells=True)
    assert report['rejected'][0]['reason'] == 'ambiguous_table_series'
