from copy import deepcopy

import pytest

from services.deep_research.verification import make_evidence, verify_claims


def evidence(key, text):
    return make_evidence({'workId': key, 'versionId': 'v1', 'contentHash': 'hash-'+key,
        'accessLevel': 'fulltext'}, text, text, location={'page': 1}, obligation_ids=[])


@pytest.mark.parametrize('kind', ['reported', 'inference'])
def test_another_claims_hardware_quote_cannot_support_this_claims_condition(kind):
    table = evidence('table', 'The quality scores are close under the reported evaluation.')
    device = evidence('device', 'All performance evaluations are conducted on an A6000 GPU.')
    claims = [{'claimId': 'c1', 'kind': kind, 'text': '论文报告接近的质量。',
        'conditions': {'context': '在A6000 GPU上评估。'}, 'evidenceRefs': [table['evidenceId']]},
        {'claimId': 'c2', 'kind': 'reported', 'text': '评估使用A6000 GPU。', 'evidenceRefs': [device['evidenceId']]}]
    sent = []
    def semantic(rows, sources):
        sent.extend(c['claimId'] for c in rows)
        return [{'claimId': c['claimId'], 'status': 'passed'} for c in rows]
    checked = verify_claims(claims, [table, device], semantic)
    assert checked['rejected'] == [{'claimId': 'c1', 'reason': 'uncited_device_condition'}]
    assert sent == ['c2'] and checked['accepted'][0]['claimId'] == 'c2'


@pytest.mark.parametrize('display,source,accepted', [
    ('RTX 3090 GPU', 'RTX3090 GPU', True),
    ('RTX 3090 Ti GPU', 'RTX3090Ti GPU', True),
    ('RTX 3090 Ti GPU', 'RTX3090 GPU', False),
    ('A6000 GPU', 'A100 GPU', False),
])
def test_device_identity_keeps_model_variants_and_still_requires_semantic_review(display, source, accepted):
    ev = evidence('p', 'All evaluations use '+source+'.')
    c = {'claimId': 'c', 'kind': 'inference', 'text': '当前证据限于'+display+'条件。', 'evidenceRefs': [ev['evidenceId']]}
    result = verify_claims([c], [ev], lambda *_: [{'claimId': 'c', 'status': 'passed'}])
    assert bool(result['accepted']) is accepted
    assert not verify_claims([c], [ev])['accepted']


def test_model_extracted_condition_is_not_original_hardware_evidence():
    ev = evidence('p', 'The measurements are reported for the selected views.')
    ev['conditions'] = {'hardware': 'A6000 GPU'}
    c = {'claimId': 'c', 'kind': 'reported', 'text': '这些结果在A6000 GPU上得到。', 'evidenceRefs': [ev['evidenceId']]}
    assert verify_claims([c], [ev], lambda *_: pytest.fail('Reject before semantic send'))['rejected'][0]['reason'] == 'uncited_device_condition'


def test_proposed_device_choice_is_not_a_reported_paper_condition():
    c = {'claimId': 'c', 'kind': 'proposal', 'text': '拟使用A6000 GPU进行尚未执行的实验。', 'evidenceRefs': []}
    assert verify_claims([c], [], lambda *_: [{'claimId': 'c', 'status': 'passed'}])['accepted']
