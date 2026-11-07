import json
import pytest
from copy import deepcopy

from services.deep_research.extraction import make_batched_extract_node
from services.deep_research.extraction_priority import prioritize_extraction_passages
from services.deep_research.verification import make_evidence


def record():
    return {'extractionPriorityVersion': 2, 'state': {'plan': [{'obligations': [
        {'obligationId': 'why', 'question': 'Why use the probabilistic method?', 'requiredSources': ['a'],
         'completionCriteria': [{'responseType': 'explanation'}]},
        {'obligationId': 'how', 'question': 'How is the model trained?', 'requiredSources': ['a'],
         'completionCriteria': [{'responseType': 'explanation'}]}]}],
        'readResults': [{'sourceId': 'pdf', 'workId': 'a', 'versionId': 'v1', 'contentHash': 'hash',
            'accessLevel': 'fulltext', 'obligationIds': ['why', 'how'], 'pages': [
                {'page': 5, 'text': 'When the loss gradient updates a weight, the later output changes. ' * 2},
                {'page': 4, 'text': 'We address the problem of local minima. Instead of direct optimization, we sample a distribution. ' * 2}]}]}}


def test_motivation_and_training_both_reach_the_first_batch_from_the_same_paper():
    r = record()
    source = r['state']['readResults'][0]
    pending = [(source, {'page': p['page']}, p['text']) for p in source['pages']]
    obligations = {o['obligationId']: o for o in r['state']['plan'][0]['obligations']}
    original = deepcopy(pending)
    selected = prioritize_extraction_passages(pending, obligations, 2)
    assert [row[1]['page'] for row in selected[:2]] == [4, 5]
    assert pending == original and len(selected) == len(pending)


@pytest.mark.parametrize('version',[2,3])
def test_three_per_passage_cap_does_not_drop_other_chunks_of_the_same_pdf(version):
    r = record()
    r['extractionPriorityVersion']=version
    r['state']['readResults'][0]['pages'] = [
        {'page': 4, 'text': 'First valid complete sentence. Second valid complete sentence. Third valid complete sentence.'},
        {'page': 5, 'text': 'A separate fourth valid sentence explaining the training update mechanism.'}]
    def update(run, change, **kwargs):
        nonlocal r
        r = change(r)
        return r
    calls = []
    def invoke(run, node, prompt, options):
        calls.append(prompt)
        assert 'passageId' in prompt and 'not the whole PDF' in prompt
        supplied = json.loads(prompt[prompt.rfind('\n[{') + 1:])
        identities = {row['location']['page']: row['passageId'] for row in supplied}
        return {'content': json.dumps([
            {'sourceId': 'pdf', 'passageId': identities[4], 'quote': sentence, 'obligationIds': ['why'], 'conditions': {}}
            for sentence in ['First valid complete sentence.', 'Second valid complete sentence.', 'Third valid complete sentence.']
        ] + [{'sourceId': 'pdf', 'passageId': identities[5],
              'quote': 'A separate fourth valid sentence explaining the training update mechanism.',
              'obligationIds': ['how'], 'conditions': {}}])}
    make_batched_extract_node(invoke, make_evidence, lambda *_: True, update)({'run_id': 'r'})
    assert len(calls) == 1 and len(r['state']['evidence']) == 4
    assert {e['location']['page'] for e in r['state']['evidence']} == {4, 5}
    assert all(e['sourceWorkId'] == 'a' and e['sourceVersionId'] == 'v1' for e in r['state']['evidence'])


@pytest.mark.parametrize('version',[2,3])
def test_an_explicit_wrong_passage_id_cannot_reassign_an_otherwise_matching_quote(version):
    r = record()
    r['extractionPriorityVersion']=version
    def update(run, change, **kwargs):
        nonlocal r
        r = change(r)
        return r
    def invoke(*args):
        return {'content': json.dumps([{'sourceId': 'pdf', 'passageId': 'X99',
            'quote': 'When the loss gradient updates a weight, the later output changes.',
            'obligationIds': ['how'], 'conditions': {}}])}
    make_batched_extract_node(invoke, make_evidence, lambda *_: True, update)({'run_id': 'r'})
    assert r['state']['evidence'] == []
