"""Drafting must retain method evidence alongside prospective output contracts."""
import copy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.design_drafting import synthesis_obligations
from services.deep_research.graph import make_synthesize_node


def test_supporting_checklist_cannot_replace_user_deliverable_or_mutate_frozen_plan():
    plan = [{'obligations': [
        {'obligationId': 'user', 'question': 'Design a comparison', 'purpose': 'answer_requirement',
         'requiredSources': ['paper'], 'requestExcerpt': 'Design a comparison',
         'completionCriteria': [{'criterionId': 'steps', 'requirement': 'Executable steps', 'responseType': 'procedure'}]},
        {'obligationId': 'background', 'question': 'What protocol did the authors use?',
         'purpose': 'supporting_research', 'requiredSources': ['paper'],
         'requestExcerpt': 'Design a comparison', 'completionCriteria': [
             {'criterionId': 'original', 'requirement': 'Original learning rate', 'responseType': 'identification'}]}]}]
    before = copy.deepcopy(plan)
    rows = synthesis_obligations(plan)
    assert rows[0] == plan[0]['obligations'][0]
    assert rows[1]['question'] == plan[0]['obligations'][1]['question']
    assert rows[1]['requiredSources'] == ['paper']
    assert 'completionCriteria' not in rows[1]
    assert plan == before


@pytest.mark.parametrize('protocol',[False,True])
def test_strict_experiment_prompt_keeps_late_method_and_named_scene_evidence(protocol):
    texts = ['Table caption: Dataset Example contains scene Sample.\nTable row: Sample | 1.0']
    texts += ['Background observation. ' * 22 for _ in range(8)]
    method = ('When training the next layer, the earlier geometry stays fixed, while its opacity '
              'is optimized jointly with the new layer. ' * 3)
    texts += [method, 'Implementation detail. ' * 15, 'Other evaluation. ' * 15]
    evidence = [{'evidenceId': f'e{i}', 'sourceWorkId': 'paper', 'sourceVersionId': 'v1',
                 'quote': text, 'sourceContext': 'Preceding subject. ' + text + 'Following condition.',
                 'accessLevel': 'fulltext', 'obligationIds': ['o'],
                 'conditions': {'scope': 'a prospective quality comparison'}} for i, text in enumerate(texts)]
    criteria = [{'criterionId': 'steps', 'requirement': '给出可执行的单因素对照步骤', 'responseType': 'procedure'}]
    record = {'question': '设计一个单场景两组实验，只比较画质，使用有限预算并标明未执行。',
              'budgetContractVersion': 1, 'hypothesisContractVersion': 1,
              'state': {'outputKind': 'experiment_design', 'metricDomains': ['quality'], 'evidence': evidence,
                        'plan': [{'obligations': [{'obligationId': 'o', 'purpose': 'answer_requirement',
                            'question': '设计对照', 'completionCriteria': criteria}]}]}}
    if protocol:record['protocolContractVersion']=1
    before = copy.deepcopy(record)
    invoke = Mock(return_value={'content': '{}'})
    make_synthesize_node(invoke, lambda *a, **k: record)({'run_id': 'r'})
    prompt = invoke.call_args.args[2]
    rows = json.loads(prompt.split('Evidence summaries:\n')[1].split('\n\nReturn ONLY')[0])
    assert len(prompt.encode()) <= 24000
    assert texts[0] in [row['quote'] for row in rows]
    assert method in [row['quote'] for row in rows]
    assert '给出可执行的单因素对照步骤' in prompt
    assert 'per-group' in prompt and 'Statistical reference' in prompt
    assert 'budgetContractVersion=1' in prompt and 'hypothesis' in prompt
    assert record == before
