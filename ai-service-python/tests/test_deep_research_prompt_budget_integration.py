"""Full request limits and evidence permissions across actual send sites."""
import json
from unittest.mock import Mock

from services.deep_research.final_coverage import audit_final_answer
from services.deep_research.graph import make_synthesize_node
from services.deep_research.repair import repair_rejected
from services.deep_research.tools import BudgetedSemanticChecker


def test_experiment_synthesis_counts_instructions_and_keeps_whole_quotes():
    evidence = [{'evidenceId': f'e{i}', 'quote': '完整引文' * 350,
                 'sourceWorkId': f'p{i % 2}', 'sourceVersionId': 'v',
                 'obligationIds': ['o']} for i in range(12)]
    record = {'question': '设计可执行的实验', 'state': {'outputKind': 'experiment_design',
              'metricDomains': ['quality'], 'evidence': evidence}}
    invoke = Mock(return_value={'content': '{}'})
    result = make_synthesize_node(invoke, lambda *a, **k: record)({'run_id': 'r'})
    prompt = invoke.call_args.args[2]
    assert len(prompt.encode('utf-8')) <= 24000
    assert 'Statistical reference' in prompt and 'designRole' in prompt
    rows = json.loads(prompt.split('Evidence summaries:\n')[1].split('\n\nReturn ONLY')[0])
    assert 0 < len(rows) < len(evidence)
    assert all(row['quote'] == evidence[0]['quote'] for row in rows)
    assert result['error_code'] == 'invalid_synthesis_response'


def test_repair_cannot_cite_row_removed_from_complete_request():
    claim = {'claimId': 'c', 'kind': 'reported', 'text': '待修订',
             'evidenceRefs': ['huge', 'small']}
    evidence = [{'evidenceId': 'huge', 'quote': '原文' * 15000},
                {'evidenceId': 'small', 'quote': '完整短引文'}]
    def invoke(prompt):
        assert len(prompt.encode('utf-8')) <= 24000
        assert '\"c\": [\"E2\"]' in prompt
        return {'content': json.dumps([{**claim, 'evidenceRefs': ['E1']}])}
    result = repair_rejected({'claims': [claim]}, {'rejected': [{'claimId': 'c'}]},
                             evidence, '核查', invoke, json.loads)
    assert result == []


def test_semantic_pass_cannot_hide_evidence_omitted_for_capacity():
    def invoke(**kwargs):
        assert len(kwargs['prompt'].encode('utf-8')) <= 24000
        return {'content': json.dumps([{'claimId': 'c', 'status': 'passed'}])}
    result = BudgetedSemanticChecker(invoke, 'r')(
        [{'claimId': 'c', 'kind': 'reported', 'text': '事实', 'evidenceRefs': ['e']}],
        [{'evidenceId': 'e', 'quote': '证据' * 15000}])
    assert result[0]['status'] == 'failed'


def test_final_audit_cannot_bind_to_omitted_source_excerpt():
    claim = {'claimId': 'c', 'kind': 'reported', 'text': '最终回答中的可核对完整句子', 'evidenceRefs': ['e']}
    binding = [{'claimId': 'c', 'excerpt': claim['text']}]
    def invoke(*args, **kwargs):
        assert len(args[2].encode('utf-8')) <= 24000
        return {'content': json.dumps([{'obligationId': 'o', 'status': 'covered',
            'bindings': binding, 'aspects': [{'aspectId': 'a', 'requirement': '必要条件',
            'status': 'covered', 'basis': {'kind': 'source', 'evidenceId': 'e',
            'excerpt': '不可展示的完整原文片段'}, 'bindings': binding}]}])}
    result = audit_final_answer('r', '', [{'obligations': [{'obligationId': 'o', 'question': '必要条件'}]}],
        [claim], [{'evidenceId': 'e', 'quote': '不可展示的完整原文片段' * 3000}], invoke, json.loads)
    assert result['status'] == 'invalid_response'
    assert result['gaps']
