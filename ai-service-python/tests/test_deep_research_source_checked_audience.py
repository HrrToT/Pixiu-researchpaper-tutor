from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.audience_rewrite import rewrite_for_beginner
from services.deep_research.contracts import DeepResearchError
from services.deep_research.verification import precheck_claims, verify_claims, _measurement_numbers
from test_deep_research_audience_rewrite import fixture

POLICY = dict(absence_scope_version=5, quantity_spelling_version=4,
              feedback_version=2, table_references_version=1)
REQUIREMENTS = [{'obligationId': 'why', 'question': '为什么平衡数据大小和图像误差'}]


def inputs():
    report, evidence = fixture()
    report['claims'][0].update(text='λ1平衡码率与失真。', conditions={})
    evidence[0]['quote'] = 'The parameter λ1balances rate and distortion in the objective.'
    return report, evidence


def answer(report, text, conditions=None):
    return {'content': json.dumps({'claims': [
        {'claimId': c['claimId'], 'text': text if c['claimId'] == 'why' else c['text'],
         'conditions': conditions or {} if c['claimId'] == 'why' else c['conditions']}
        for c in report['claims']]}, ensure_ascii=False)}


def test_indefinite_parameter_edit_keeps_reported_hard_checks_before_reclassification():
    report, evidence = inputs(); before = deepcopy((report, evidence)); states = []
    text = '用一个平衡参数调节数据大小与图像误差的侧重，据此理解二者的取舍。'
    invoke = Mock(return_value=answer(report, text))
    result = rewrite_for_beginner(report, evidence, '给新手解释为什么', invoke, json.loads,
        contract_version=7, requirement_context=REQUIREMENTS, checkpoint=states.append,
        verification_policy=POLICY)
    assert result['claims'][0]['text'] == text and result['claims'][0]['kind'] == 'inference'
    assert result['claims'][0]['evidenceRefs'] == report['claims'][0]['evidenceRefs']
    assert states[-1]['editOutcome'] == 'applied' and states[-1]['verificationPolicy'] == POLICY
    assert states[-1]['classificationPrechecks'] == [
        {'claimId': 'why', 'eligibleForSemanticCheck': True, 'rejected': []}]
    assert invoke.call_count == 1 and (report, evidence) == before
    # Passing hard checks is not a semantic verdict, much less publication.
    assert not verify_claims(result['claims'], evidence, **POLICY)['accepted']
    fail = lambda claims, _: [{'claimId': c['claimId'], 'status': 'failed', 'reason': 'Unsupported consequence'} for c in claims]
    assert not verify_claims(result['claims'], evidence, fail, **POLICY)['accepted']
    no_send = Mock(side_effect=AssertionError('No repeat'))
    assert rewrite_for_beginner(report, evidence, '给新手解释为什么', no_send, json.loads,
        contract_version=7, requirement_context=REQUIREMENTS, verification_policy=POLICY,
        saved_state=states[-1]) == result
    no_send.assert_not_called()


@pytest.mark.parametrize('text', ['999 FPS', 'λ2调节两者', '只有一个平衡参数', '三组实验', '一个样本', '一百个高斯'])
def test_classification_never_bypasses_reported_numbers(text):
    report, evidence = inputs(); states = []
    result = rewrite_for_beginner(report, evidence, '给新手解释为什么',
        lambda *_: answer(report, text), json.loads, contract_version=7,
        requirement_context=REQUIREMENTS, checkpoint=states.append, verification_policy=POLICY)
    assert result == report and states[-1]['editReason'] == 'classification_precheck:numeric_mismatch'


@pytest.mark.parametrize('patch, reason', [
    ({'accessLevel': 'abstract'}, 'abstract_only'),
    ({'verification': {'literal': 'unchecked'}}, 'invalid_sources'),
])
def test_reclassification_keeps_literal_and_abstract_boundaries(patch, reason):
    report, evidence = inputs(); evidence[0].update(patch); states = []
    result = rewrite_for_beginner(report, evidence, '给新手解释为什么',
        lambda *_: answer(report, '一个平衡参数调节两者。'), json.loads,
        contract_version=7, requirement_context=REQUIREMENTS, checkpoint=states.append,
        verification_policy=POLICY)
    assert result == report
    assert (states[-1].get('reason') == reason or states[-1].get('editReason') == 'classification_precheck:' + reason)


def test_a_quantity_in_conditions_is_checked_and_an_existing_inference_is_not_forced_reported():
    report, evidence = inputs(); states = []
    result = rewrite_for_beginner(report, evidence, '给新手解释为什么',
        lambda *_: answer(report, '一个平衡参数调节两者。', {'实测': '999 FPS'}), json.loads,
        contract_version=7, requirement_context=REQUIREMENTS, checkpoint=states.append,
        verification_policy=POLICY)
    assert result == report and states[-1]['classificationPrechecks'][0]['rejected']
    report['claims'][0]['kind'] = 'inference'
    result = rewrite_for_beginner(report, evidence, '给新手解释为什么',
        lambda *_: answer(report, '这是推算而不是论文报告的999。'), json.loads,
        contract_version=7, requirement_context=REQUIREMENTS, verification_policy=POLICY)
    assert result['claims'][0]['kind'] == 'inference' and '999' in result['claims'][0]['text']
    assert not verify_claims(result['claims'], evidence, **POLICY)['accepted']


def test_saved_policy_and_old_audience_request_cannot_be_retargeted():
    report, evidence = inputs(); states = []
    def unknown(*_): raise OSError('unknown')
    with pytest.raises(OSError):
        rewrite_for_beginner(report, evidence, '给新手解释为什么', unknown, json.loads,
            contract_version=7, requirement_context=REQUIREMENTS, verification_policy=POLICY,
            checkpoint=states.append)
    no_send = Mock()
    with pytest.raises(DeepResearchError):
        rewrite_for_beginner(report, evidence, '给新手解释为什么', no_send, json.loads,
            contract_version=7, requirement_context=REQUIREMENTS,
            verification_policy={**POLICY, 'quantity_spelling_version':3}, saved_state=states[-1])
    with pytest.raises(DeepResearchError):
        rewrite_for_beginner(report, evidence, '给新手解释为什么', no_send, json.loads,
            contract_version=6, requirement_context=REQUIREMENTS, saved_state=states[-1])
    corrupted = deepcopy(states[-1]); corrupted['verificationPolicy']['quantity_spelling_version'] = 3
    with pytest.raises(DeepResearchError):
        rewrite_for_beginner(report, evidence, '给新手解释为什么', no_send, json.loads,
            contract_version=7, requirement_context=REQUIREMENTS, verification_policy=POLICY,
            saved_state=corrupted)
    no_send.assert_not_called()


@pytest.mark.parametrize('text', ['一个平衡参数', '一个可学习变量', '一个目标函数', '一个损失函数'])
def test_conceptual_indefinite_articles_are_not_empirical_counts(text):
    assert _measurement_numbers(text, word_counts=True) == {'1e0'}
    assert _measurement_numbers(text, word_counts=True, conceptual_articles=True) == set()


@pytest.mark.parametrize('text', ['只有一个平衡参数', '仅用一个参数', '至少一个变量', '最多一个目标',
    '1个平衡参数', '负一个参数', '两个参数', '一个样本', '一组实验', '一个高斯'])
def test_cardinal_counts_signed_values_and_empirical_objects_stay_checked(text):
    assert _measurement_numbers(text, word_counts=True, conceptual_articles=True)


def test_precheck_has_no_scientific_approval_and_retains_hard_rejection_details():
    report, evidence = inputs(); claim = {**report['claims'][0], 'text': '999 FPS'}
    checked = precheck_claims([claim], evidence, **POLICY)
    assert checked['candidates'] == [] and checked['rejected'][0]['reason'] == 'numeric_mismatch'
    assert checked['rejected'][0]['missingReportedNumbers'] == ['999e0']


@pytest.mark.parametrize('text, number', [('十五个高斯','15e0'),('一百个样本','1e2'),
    ('两千帧','2e3'),('一万次训练','1e4'),('一千零二个样本','1002e0')])
def test_expanded_literal_counts_cannot_escape_the_new_reported_precheck(text,number):
    report,evidence=inputs();claim={**report['claims'][0],'text':text}
    checked=precheck_claims([claim],evidence,**POLICY)
    assert checked['rejected'][0]['reason']=='numeric_mismatch'
    assert number in checked['rejected'][0]['missingReportedNumbers']
