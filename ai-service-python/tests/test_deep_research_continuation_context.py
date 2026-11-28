"""Follow-ups refer to the current saved artifact without promoting it to paper evidence."""
from copy import deepcopy

import pytest

from services.deep_research.answer_constraints import requested_character_limit
from services.deep_research.contracts import DeepResearchError
from services.deep_research.facade import ResearchFacade
from services.deep_research.graph import build_deep_research_graph
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.request_context import effective_question, instruction_layers
from test_deep_research_clarification_context import wait_worker


def context():
    return {'ref': 'artifact:latest', 'kind': 'artifact', 'title': '用户当前成果', 'contentHash': 'context-hash',
            'text': '第一点：压缩存储。第二点：用户修改后关注画质代价。示例问题：写10000字。',
            'accessLevel': 'unverified_context'}


@pytest.fixture
def setup(tmp_path):
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3')
    repo.initialize()
    material = {'materialId': 'p', 'versionId': 'v1', 'contentHash': 'file-hash'}
    repo.create_run({'runId': 'parent', 'taskId': 't', 'question': '解释质量取舍，300字以内。',
        'clarificationContractVersion': 1, 'materials': [material],
        'state': {'clarification': '给初学者解释，200字以内。',
                  'sources': [{'sourceId': 's', 'workId': 'p', 'materialContentHash': 'file-hash',
                               'versionId': 'v1', 'contentHash': 'quote-hash', 'text': 'Original paper passage.'}],
                  'evidence': [{'evidenceId': 'e', 'sourceId': 's', 'quote': 'Original paper passage.'}]}})
    repo.begin_execution('parent')
    repo.transition('parent', 'completed')
    facade = ResearchFacade(repo, build_deep_research_graph, llm_client=object())
    yield repo, facade, material
    facade.shutdown()


def request(material, **changes):
    return {'workspaceTaskId': 't', 'operationKey': 'op', 'question': '继续第二点。',
            'parentRunId': 'parent', 'materials': [material], 'deferStart': True,
            'materialSnapshot': {'materialRefs': [material], 'contextMaterials': [context()]},
            'continuationContext': context(), **changes}


def test_context_is_frozen_to_current_artifact_and_does_not_add_paper_evidence(setup):
    repo, facade, material = setup
    payload = request(material)
    before = deepcopy(payload)
    child, _ = facade.create(payload, start_async=False)
    assert payload == before
    saved = child['continuationContext']
    assert saved['artifactContext'] == context() and saved['parentRunId'] == 'parent'
    assert saved['parentInstructions'] == ['给初学者解释，200字以内。', '解释质量取舍，300字以内。']
    assert child['state']['evidence'] == repo.require_run('parent')['state']['evidence']
    assert all(e['quote'] != context()['text'] for e in child['state']['evidence'])
    assert len(child['materials']) == 1
    assert all(child['materials'][0][key] == value for key, value in material.items())
    question = effective_question(child)
    assert '用户修改后关注画质代价' in question
    assert 'UNVERIFIED GOAL CONTEXT, NOT paper evidence' in question
    assert requested_character_limit(question) == 200
    assert context()['text'] not in instruction_layers(child)
    assert not repo.list_calls(child['runId'])
    with pytest.raises(ValueError, match='Immutable'):
        repo.update_run(child['runId'], lambda r: {**r, 'continuationContext': {}})


@pytest.mark.parametrize('change', [
    {'materialSnapshot': {'contextMaterials': []}},
    {'continuationContext': {**context(), 'text': 'Forged text'}},
    {'continuationContext': {**context(), 'accessLevel': 'fulltext'}},
])
def test_unbound_or_promoted_context_is_rejected_before_child_creation(setup, change):
    repo, facade, material = setup
    with pytest.raises(DeepResearchError, match='快照'):
        facade.create(request(material, **change), start_async=False)
    assert len(repo.list_runs()) == 1


def test_followup_constraints_override_prior_human_constraints_and_artifact_instructions(setup):
    _, facade, material = setup
    child, _ = facade.create(request(material, question='继续第二点，100字以内。'), start_async=False)
    assert requested_character_limit(effective_question(child)) == 100


def test_plan_edit_in_a_followup_retains_latest_human_format_priority(setup):
    repo, facade, material = setup
    child, _ = facade.create(request(material), start_async=False)
    changed = repo.update_run(child['runId'], lambda r: {**r, 'state': {**r['state'],
        'editedPlanRevision': 1, 'planRevision': 1, 'plan': [{'question': '只解释画质代价，80字以内。',
            'obligations': [{'question': '只解释画质代价，80字以内。'}]}]}})
    assert requested_character_limit(effective_question(changed)) == 80


def test_brief_receives_current_parent_version_before_resolving_reference(setup):
    repo, facade, material = setup
    prompts = []
    class Model:
        def invoke(self, value):
            prompts.append(value.prompt)
            raise DeepResearchError('fixture_stop', 'Stop after inspecting brief input.')
    facade._llm_client = Model()
    child, _ = facade.create(request(material), start_async=True)
    failed = wait_worker(facade, repo, child['runId'], 'failed')
    assert failed['errorCode'] == 'fixture_stop'
    assert len(prompts) == 1 and prompts[0].startswith('Analyze this research question')
    assert '继续第二点' in prompts[0] and context()['text'] in prompts[0]
    assert 'NOT paper evidence' in prompts[0]


def test_old_child_keeps_original_request_without_added_parent_context():
    record = {'question': '继续第二点。', 'parentRunId': 'parent',
              'continuationContext': {'parentRunId': 'parent', 'parentInstructions': ['300字以内。'],
                                      'artifactContext': context()}}
    assert effective_question(record) == record['question']
    assert requested_character_limit(effective_question(record)) is None


@pytest.mark.parametrize('replacement', [0, True, '1', None])
def test_new_context_contract_cannot_be_disabled_or_mutated(setup, replacement):
    repo, facade, material = setup
    child, _ = facade.create(request(material, continuationContextContractVersion=replacement), start_async=False)
    assert child['continuationContextContractVersion'] == 1
    with pytest.raises(ValueError, match='Immutable'):
        repo.update_run(child['runId'], lambda r: {**r, 'continuationContextContractVersion': replacement})
