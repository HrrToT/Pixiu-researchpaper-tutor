from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.result_attribution import targets, validate_audit
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.verification import precheck_claims, verify_claims
from test_deep_research_synthesis_premises import claim, evidence


@pytest.mark.parametrize('text', [
    '3DGStream的主表FPS条件未在提供的证据中说明。',
    '论文B的设置没有在当前材料中找到。',
    '其输入未被所选证据说明。',
    '提供的证据中未说明论文B的设置。',
    'Paper B settings are not specified in the supplied evidence.',
])
def test_unseen_pool_claim_cannot_use_only_another_papers_reference(text):
    support=[evidence('e', 'Paper A uses a fixed GPU.')]
    target=claim(text, kind='inference')
    before=deepcopy((target,support))
    check=Mock()
    result=verify_claims([target],support,check,absence_scope_version=7)
    assert result['rejected'][0]['reason']=='absence_not_established'
    check.assert_not_called()
    assert (target,support)==before


def test_pool_omission_does_not_gain_authority_from_unrelated_explicit_negative_quote():
    support=[evidence('e', 'We did not evaluate another dataset.')]
    target=claim('论文B的条件未在提供的证据中说明。',kind='inference')
    assert precheck_claims([target],support,absence_scope_version=6)['candidates']
    assert precheck_claims([target],support,absence_scope_version=7)['rejected']
    for text in ['这些片段不足以建立同条件速度排名。', '作者没有评估另一个数据集。']:
        assert precheck_claims([claim(text,kind='inference')],support,absence_scope_version=7)['candidates']


def fixture():
    target=claim('A的主表FPS是在同一GPU下测得的。',('m','p'),'inference')
    support=[evidence('m', 'The rendering FPS was measured on a fixed GPU.', 'a', 'Table 1'),
             evidence('p', 'Table 1. Quantitative comparison on the benchmark.', 'a', 'Table 1')]
    row={**targets(target)[0], 'resultRole':'primary_comparison', 'supported':True,
        'measurementPremise':{'evidenceId':'m','path':['quote']},
        'purposePremise':{'evidenceId':'p','quote':support[1]['quote']}}
    return target,support,{'resultPurposeAudit':[row]}


def test_main_result_assertions_are_audited_but_no_ranking_and_negative_role_are_not_promoted():
    for text in ['A的主表FPS是在3090上测得的，因此不能排名。',
                 'A的主表FPS来自GPU实验。', 'Main table FPS was measured on a GPU.']:
        assert targets(claim(text,kind='inference'))
    for text in ['无法凭各自主表FPS判断同条件速度。', '这里的FPS来自参数扫描，并非主表。',
                 '这些证据不足以建立主表FPS的可比性。']:
        assert targets(claim(text,kind='inference'))==[]


def test_actual_point_count_sweep_cannot_supply_main_result_purpose():
    target,support,verdict=fixture()
    support[1]['quote']='Table 4. Experiments on FPS with respect to number of 3D Gaussians.'
    support[1]['location']['section']='Table 1'  # Metadata alone cannot confer primary purpose.
    verdict['resultPurposeAudit'][0]['purposePremise']['quote']=support[1]['quote']
    assert validate_audit(target,verdict,support)==['result_purpose_not_established']


@pytest.mark.parametrize('mutation, error', [
    ('source','result_purpose_source_mismatch'), ('version','result_purpose_source_mismatch'),
    ('foreign','result_purpose_premises_not_bound'), ('table','result_purpose_table_mismatch'),
    ('missing','result_purpose_audit_missing'), ('target','result_purpose_target_not_bound'),
])
def test_other_paper_version_table_or_true_prefix_cannot_license_attribution(mutation,error):
    target,support,verdict=fixture()
    if mutation=='source': support[1]['sourceWorkId']='b'
    if mutation=='version': support[1]['sourceVersionId']='other-version'
    if mutation=='foreign': target['evidenceRefs']=['m']
    if mutation=='table':
        support[1]['quote']='Table 2. Quantitative comparison on the benchmark.'
        support[1]['location']['section']='Table 2'
        verdict['resultPurposeAudit'][0]['purposePremise']['quote']=support[1]['quote']
    if mutation=='missing': verdict={}
    if mutation=='target': verdict['resultPurposeAudit'][0]['statementExcerpt']='同一GPU'
    assert validate_audit(target,verdict,support)==[error]


def test_production_verifier_enforces_new_audit_after_a_model_false_pass():
    target,support,verdict=fixture()
    verdict.update(claimId='c',status='passed')
    before=deepcopy((target,support))
    invoke=Mock(return_value={'content':json.dumps([{'claimId':'c','status':'passed'}])})
    old=BudgetedSemanticChecker(invoke,'r')([target],support)
    assert old[0]['status']=='passed'  # Historical path unchanged.
    checked=BudgetedSemanticChecker(invoke,'r',result_attribution=True)([target],support)
    assert checked[0]['status']=='failed' and 'result_purpose_audit_missing' in checked[0]['reason']
    assert 'resultPurposeAudit' in invoke.call_args.kwargs['prompt']
    # Correct structural linkage still relies on the independent semantic verdict.
    verdict['resultPurposeAudit'][0]['measurementPremise']['evidenceId']='E1'
    verdict['resultPurposeAudit'][0]['purposePremise']['evidenceId']='E2'
    invoke.return_value={'content':json.dumps([verdict])}
    assert BudgetedSemanticChecker(invoke,'r',result_attribution=True)([target],support)[0]['status']=='passed'
    verdict['status']='failed';verdict['reason']='Caption is for a different experiment.'
    invoke.return_value={'content':json.dumps([verdict])}
    assert BudgetedSemanticChecker(invoke,'r',result_attribution=True)([target],support)[0]['status']=='failed'
    assert (target,support)==before
