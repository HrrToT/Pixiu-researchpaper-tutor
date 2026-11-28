from unittest.mock import Mock

import pytest

from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.verification import precheck_claims, verify_claims


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


@pytest.mark.parametrize('text,located,allowed', [
    ('所引论文段落未说明父子优化器状态。', True, True),
    ('所引论文段落未说明父子优化器状态。', False, False),
    ('所引论文未说明父子优化器状态。', True, False),
    ('所引论文段落未说明父子优化器状态；整篇论文未报告该规则。', True, False),
    ('所引论文段落未说明父子优化器状态，详见E5。', True, False),
])
def test_cited_passage_scope_needs_located_text_and_excludes_whole_paper_claims(text, located, allowed):
    claim, evidence = fixture(text)
    if located:
        evidence['location'] = {'page': 5, 'sourcePassageStart': 600, 'sourcePassageEnd': 850}
    result = precheck_claims([claim], [evidence], absence_scope_version=8, cited_passage_scope=True)
    assert bool(result['rejected']) is not allowed


@pytest.mark.parametrize('text,located,allowed', [
    ('作者提出可探索点云压缩，但这些引文未给出具体压缩操作。', True, True),
    ('引文未给出额外压缩操作。', True, True),
    ('引文未给出额外压缩操作。', False, False),
    ('引文显示整篇论文未给出额外压缩操作。', True, False),
    ('该示例引文未说明这些运行是否使用相同硬件。', True, True),
    ('该示例引文未说明这些运行是否使用相同硬件。', False, False),
    ('该示例引文未说明这些运行是否使用相同硬件，所以整篇论文未报告配置。', True, False),
    ('结果没有在所引论文中被披露。', True, False),
    ('这些证据未说明该方法在哪种硬件上渲染。', True, False),
])
def test_comparison_specific_quotation_scope_preserves_whole_paper_guard(text, located, allowed):
    claim, evidence = fixture(text)
    if located:
        evidence['location'] = {'page': 5, 'sourcePassageStart': 200, 'sourcePassageEnd': 310}
    checked = precheck_claims([claim], [evidence], absence_scope_version=9)
    assert bool(checked['rejected']) is not allowed


@pytest.mark.parametrize('text,rejected', [
    ('论文将点云压缩列为未来可探索的方向，而非此处已实施的压缩步骤。', True),
    ('论文仅建议探索点云压缩，所引材料不能量化其成本。', True),
    ('原文建议探索点云压缩；这些引文不足以量化额外成本。', False),
    ('不能据此认为论文仅建议探索点云压缩。', False),
    ('论文提出了一项可在未来检验的优化。', False),
])
def test_future_work_note_does_not_establish_exclusion_of_implemented_work(text, rejected):
    claim, evidence = fixture(text)
    evidence['quote'] = ('It would be interesting to adapt compression for this representation. '
                         'We do not report other scene settings in this figure.')
    assert not precheck_claims([claim], [evidence], absence_scope_version=9)['rejected']
    checked = precheck_claims([claim], [evidence], absence_scope_version=10)
    assert bool(checked['rejected']) is rejected
    if rejected:
        assert checked['rejected'][0]['reason'] == 'absence_not_established'
        assert '未来建议本身不能证明' in checked['rejected'][0]['detail']


def test_explicit_implementation_boundary_still_requires_semantic_review():
    claim, evidence = fixture('论文将点云压缩列为未来可探索的方向，而非此处已实施的压缩步骤。')
    evidence['quote'] = 'Point cloud compression was not implemented in this study.'
    check = Mock(return_value=[{'claimId': 'c', 'status': 'failed'}])
    result = verify_claims([claim], [evidence], check, absence_scope_version=10)
    check.assert_called_once()
    assert not result['accepted']


@pytest.mark.parametrize('replacement', [None, True, '2', 0, 1, 2])
def test_server_scope_version_is_frozen_and_applies_to_both_verification_passes(tmp_path, replacement):
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **_: None, llm_client=object())
    try:
        run, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'o', 'question': '解释方法',
            'absenceScopeContractVersion': replacement, 'deferStart': True}, start_async=False)
        assert run['absenceScopeContractVersion'] == 8
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
