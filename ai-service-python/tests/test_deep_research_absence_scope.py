from unittest.mock import Mock

import pytest

from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.verification import verify_claims


def fixture(text):
    evidence = {'evidenceId': 'e', 'quote': 'This approach falters when faced with objects not present in the initial frame.',
                'accessLevel': 'fulltext', 'verification': {'literal': 'passed'}}
    claim = {'claimId': 'c', 'kind': 'inference', 'text': text, 'evidenceRefs': ['e']}
    return claim, evidence


@pytest.mark.parametrize('text', [
    '新物体在初始帧中不存在对应内容，仅变换已有表示不足以重建它。',
    '论文指出，初始帧中不存在的新物体需要另行表示。',
    '该方法不包含一个独立的颜色网络。',
])
def test_method_negative_premise_reaches_semantics_without_becoming_a_fact(text):
    claim, evidence = fixture(text)
    check = Mock(return_value=[{'claimId': 'c', 'status': 'failed'}])
    result = verify_claims([claim], [evidence], check, absence_scope_version=1)
    check.assert_called_once()
    assert not result['accepted']
    assert result['rejected'][0]['reason'] != 'absence_not_established'
    check.return_value = [{'claimId': 'c', 'status': 'passed'}]
    assert verify_claims([claim], [evidence], check, absence_scope_version=1)['accepted']
    assert not verify_claims([claim], [evidence], absence_scope_version=1)['accepted']


@pytest.mark.parametrize('text', [
    '论文不存在其他场景的实验。', '跨硬件评测不存在。', '没有报告其他场景。',
    '当前取得片段可参考，但论文没有报告其他场景。',
    '摘要不包含实验结果。', 'The paper does not report other evaluations.',
])
def test_unestablished_publication_absence_still_fails_before_semantics(text):
    claim, evidence = fixture(text)
    check = Mock()
    result = verify_claims([claim], [evidence], check, absence_scope_version=1)
    assert result['rejected'][0]['reason'] == 'absence_not_established'
    check.assert_not_called()


def test_scope_rule_is_opt_in_and_does_not_reinterpret_old_runs():
    claim, evidence = fixture('初始帧中不存在新出现的物体。')
    check = Mock()
    assert verify_claims([claim], [evidence], check)['rejected'][0]['reason'] == 'absence_not_established'
    check.assert_not_called()


@pytest.mark.parametrize('replacement', [None, True, '2', 0, 1, 2])
def test_server_scope_version_is_frozen_and_applies_to_both_verification_passes(tmp_path, replacement):
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        run, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'o', 'question': '解释方法',
            'absenceScopeContractVersion': replacement, 'deferStart': True}, start_async=False)
        assert run['absenceScopeContractVersion'] == 4
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(run['runId'], lambda r: {**r, 'absenceScopeContractVersion': replacement})
        claim, evidence = fixture('初始帧中不存在新物体。')
        check = Mock(return_value=[{'claimId': 'c', 'status': 'passed'}])
        verifier = facade._get_verify_claims(run['runId'])
        assert verifier([claim], [evidence], check)['accepted']
        assert verifier([claim], [evidence], check)['accepted']
        repo.create_run({'runId': 'legacy', 'taskId': 't'})
        assert facade._get_verify_claims('legacy')([claim], [evidence], check)['rejected']
    finally:
        facade.shutdown()
