"""A persisted pre-verification checkpoint cannot override a human-edited plan."""
from copy import deepcopy
import json
import sqlite3

import pytest

from llm.provider import LLMResult, LLMUsage
from services.deep_research.contracts import DeepResearchError
from services.deep_research.facade import ResearchFacade
from services.deep_research.graph import build_deep_research_graph
from services.deep_research.plan_resume import checkpoint_patch
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.request_context import effective_question
from test_deep_research_clarification_context import wait_worker


def plan(question, oid='old'):
    return [{'itemId': 'i', 'question': question, 'obligations': [{'obligationId': oid,
        'question': question, 'requiredSources': ['p'], 'completionCriteria': [
            {'criterionId': 'conditions', 'requirement': question, 'responseType': 'explanation'}]}]}]


class Model:
    def __init__(self, relevant):
        self.relevant = relevant
        self.prompts = []

    def invoke(self, request):
        self.prompts.append(request.prompt)
        if request.prompt.startswith('For each evidence-obligation pair'):
            content = [{'pairId': 'R1', 'relevant': self.relevant}]
        elif 'Extract' in request.prompt[:100] or 'extract' in request.prompt[:100]:
            content = []
        elif 'Research questions' in request.prompt:
            raise DeepResearchError('fixture_stop', 'Stop at the new synthesis input; no content score.')
        else:
            raise AssertionError('Unexpected old-plan node: ' + request.prompt[:120])
        return LLMResult('fixture', 'fixture', json.dumps(content), LLMUsage(10, 10, 20))


@pytest.mark.parametrize('checkpoint_exists', [True, False])
@pytest.mark.parametrize('relevant', [True, False])
def test_edit_restarts_at_evidence_assessment_not_old_verification(tmp_path, checkpoint_exists, relevant):
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3')
    repo.initialize()
    source = {'sourceId': 's', 'workId': 'p', 'ownerMaterialId': 'p', 'versionId': 'v1',
              'contentHash': 'hash', 'text': 'The method uses image reconstruction supervision.',
              'accessLevel': 'fulltext', 'sourceKind': 'task_paper', 'obligationIds': ['old'],
              'location': {'page': 2}}
    evidence = {'evidenceId': 'e', 'sourceId': 's', 'sourceWorkId': 'p', 'ownerMaterialId': 'p',
        'sourceVersionId': 'v1', 'quote': source['text'], 'contentHash': 'hash',
        'verification': {'literal': 'passed', 'semantic': 'passed'}, 'obligationIds': ['old']}
    old_report = {'claims': [{'claimId': 'old', 'text': 'OLD DRAFT'}]}
    repo.create_run({'runId': 'r', 'taskId': 't', 'question': '解释原方法，300字以内。',
        'planEditContractVersion': 1, 'planResumeContractVersion': 1,
        'planCompletionContractVersion': 1, 'adaptiveResearchContractVersion': 1,
        'sourcePolicy': {'mode': 'task_only'},
        'materials': [{'materialId': 'p', 'versionId': 'v1'}],
        'state': {'plan': plan('原问题'), 'planRevision': 0, 'sources': [source], 'evidence': [evidence],
                  'reportBody': old_report, 'repairCompleted': True,
                  'verifiedReport': {'verifiedClaims': old_report['claims']}}})
    repo.begin_execution('r')
    if checkpoint_exists:
        with sqlite3.connect(str(repo.db_path) + '.checkpoints', check_same_thread=False) as conn:
            graph = build_deep_research_graph(llm_invoke=lambda *_: pytest.fail('No model at fixture setup'),
                retrieve_fn=lambda *_: [], read_fn=lambda *_: {}, scope_validator=lambda *_: True,
                make_evidence_fn=lambda *_: {}, coverage_gaps_fn=lambda *_: [], verify_claims_fn=lambda *_: {},
                repo_update=repo.update_run, repo_publish=repo.publish_report, validate_plan_fn=lambda p: p,
                checkpoint_conn=conn)
            config = {'configurable': {'thread_id': 'r'}}
            graph.update_state(config, {'run_id': 'r', 'execution_epoch': 1, 'plan_revision': 0,
                'report_version_id': 'OLD', 'stop_reason': 'covered', 'budget_exhausted': True}, as_node='synthesize')
            assert graph.get_state(config).next == ('verify',)
    paused = repo.transition('r', 'paused')
    model = Model(relevant)
    retrieves = []
    def retrieve(query, pdf_id, limit=5):
        retrieves.append((query, pdf_id))
        return []
    facade = ResearchFacade(repo, build_deep_research_graph, llm_client=model,
        retriever=retrieve, source_reader=lambda *_: {}, scope_validator=lambda *_: True)
    try:
        edited = facade.action('r', 'plan', {'requestId': 'edit', 'expectedRunRevision': paused['runRevision'],
            'planRevision': 0, 'plan': plan('只解释新的训练信号，200字以内。', 'new')})
        saved = repo.require_run('r')
        assert saved['state']['planEditHistory'][0]['retiredOutputs']['reportBody'] == old_report
        assert 'reportBody' not in saved['state'] and 'repairCompleted' not in saved['state']
        assert saved['state']['evidence'][0]['quote'] == evidence['quote']
        assert saved['state']['evidence'][0]['obligationIds'] == ['new']
        assert saved['state']['evidence'][0]['verification']['semantic'] == 'unchecked'
        frozen = deepcopy((saved['materials'], saved['sourcePolicy'], saved['budget']))
        assert not repo.list_calls('r')  # Editing alone never starts work.
        facade.action('r', 'resume', {'requestId': 'resume', 'expectedRunRevision': edited['runRevision']})
        final = wait_worker(facade, repo, 'r', 'failed')
        assert final['errorCode'] == 'fixture_stop'
        assert model.prompts[0].startswith('For each evidence-obligation pair')
        assert '新的训练信号' in model.prompts[0] and 'new' in model.prompts[0]
        assert 'Human-edited research targets' in model.prompts[-1]
        assert '200' in model.prompts[-1] and 'OLD DRAFT' not in model.prompts[-1]
        assert bool(retrieves) is (not relevant)
        assert all('新的训练信号' in query and pdf_id == 'p' for query, pdf_id in retrieves)
        assert final['materials'] == frozen[0] and final['sourcePolicy'] == frozen[1]
        assert final['budget']['maxTokens'] == frozen[2]['maxTokens']
        assert not final.get('publication', {}).get('published')
        assert final['state']['planRevision'] == 1
    finally:
        facade.shutdown()


def test_already_rebased_checkpoint_is_not_rebased_again():
    record = {'planResumeContractVersion': 1, 'state': {'editedPlanRevision': 2, 'planRevision': 2}}
    assert checkpoint_patch(record, {'channel_values': {'plan_revision': 2}}) is None
    with pytest.raises(DeepResearchError, match='版本'):
        checkpoint_patch({**record, 'state': {**record['state'], 'planRevision': 3}}, None)


def test_old_runs_keep_their_checkpoint_and_request_context():
    record = {'question': 'Original', 'state': {'editedPlanRevision': 1, 'planRevision': 1}}
    assert checkpoint_patch(record, None) is None
    assert effective_question(record) == 'Original'


@pytest.mark.parametrize('replacement', [0, True, '1', None])
def test_plan_resume_contract_is_server_owned_and_immutable(tmp_path, replacement):
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3')
    repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        run, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'op', 'question': '研究方法',
                               'planResumeContractVersion': replacement, 'deferStart': True}, start_async=False)
        assert run['planResumeContractVersion'] == 1
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(run['runId'], lambda r: {**r, 'planResumeContractVersion': replacement})
    finally:
        facade.shutdown()
