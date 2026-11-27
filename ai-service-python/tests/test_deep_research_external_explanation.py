from services.deep_research.external_explanation import MARKER, enabled, prioritize


def test_external_explanation_is_limited_to_explicit_external_surveys():
    record = {MARKER: 1, 'sourcePolicy': {'mode': 'external_only'}}
    assert enabled(record, 'direction_survey')
    assert not enabled(record, 'claim_verification')
    assert not enabled({'sourcePolicy': record['sourcePolicy']}, 'direction_survey')
    assert not enabled({**record, 'sourcePolicy': {'mode': 'task_only'}}, 'direction_survey')


def test_external_navigation_keeps_the_same_revision_and_complete_groups():
    def passage(eid, quote, *, revision='v2', literal='passed'):
        return {'evidenceId': eid, 'quote': quote, 'sourceVersionId': revision,
                'verification': {'literal': literal}}

    storage = passage('storage', 'We selectively retrieve critical vectors and offload most vectors to CPU memory.')
    split = passage('split', 'We persist selected vectors on GPU devices and compute in parallel.')
    merge = passage('merge', 'We combine the partial outputs using the following equations.')
    foreign = passage('foreign', storage['quote'], revision='v1')
    unchecked = passage('unchecked', merge['quote'], literal='unchecked')
    background = passage('background', 'The paper reports several measurements.')
    window = passage('window', 'The static pattern contains initial tokens and tokens in the local window.')
    wrong_window = passage('wrong_window', window['quote'], revision='v1')
    plan = [{'obligations': [
        {'obligationId': 'first', 'question': '怎样读取历史向量，其余向量存放在哪里？', 'requiredSources': ['v2']},
        {'obligationId': 'second', 'question': 'CPU 和 GPU 分别计算什么，如何合并？', 'requiredSources': ['v2']},
    ]}]
    selected, bundles = prioritize([foreign, unchecked, storage, split, merge], [background], [], plan)
    assert selected == [storage, split, merge, background]
    assert [bundle['evidenceIds'] for bundle in bundles] == [['storage'], ['split', 'merge']]
    assert all(bundle['source'] == 'v2' for bundle in bundles)
    _, incomplete = prioritize([foreign, unchecked, storage, split], [background], [], plan)
    assert [bundle['evidenceIds'] for bundle in incomplete] == [['storage']]
    selected, bundles = prioritize([wrong_window, storage, split, merge, window], [background], [], plan,
                                   include_selection_rule=True)
    assert selected == [storage, split, merge, window, background]
    assert bundles[1]['evidenceIds'] == ['split', 'merge', 'window']


def test_external_layer_selection_prioritizes_literal_ranking_scope_for_the_requested_revision():
    question = '每层拿到容量后又怎样决定保留哪些内容'
    plan = [{'obligations': [{'obligationId': 'retention', 'question': question,
                              'requiredSources': ['arxiv:2400.00000v2']}]}]
    background = {'evidenceId': 'summary', 'quote': 'The cache size varies over layers.'}
    scope = {'evidenceId': 'method', 'sourceVersionId': 'arxiv:2400.00000v2',
             'verification': {'literal': 'passed'},
             'quote': 'For each head, the tokens with the highest scores are retained.'}
    wrong_version = {**scope, 'evidenceId': 'v1', 'sourceVersionId': 'arxiv:2400.00000v1'}
    unchecked = {**scope, 'evidenceId': 'unchecked', 'verification': {'literal': 'unchecked'}}
    coarse = {**scope, 'evidenceId': 'coarse', 'quote': 'The highest scores are retained.'}
    evidence = [wrong_version, unchecked, coarse, scope]

    assert prioritize(evidence, [background], [], plan) == ([background], [])
    ordered, bundles = prioritize(evidence, [background], [], plan, include_selection_unit=True)
    assert ordered == [scope, background]
    assert bundles[0]['obligationId'] == 'retention' and bundles[0]['evidenceIds'] == ['method']

    plan[0]['obligations'][0]['question'] = '各层的缓存容量为何不同'
    assert prioritize(evidence, [background], [], plan, include_selection_unit=True) == ([background], [])
