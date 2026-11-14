import json
from copy import deepcopy
from unittest.mock import Mock
import pytest
from services.deep_research.general_advice import eligible,enabled
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.verification import make_evidence
from services.deep_research.reporting import render_report,publication_notices,conversation_summary
from services.deep_research.answer_constraints import visible_count


def fixture():
    quote='Pruning reduces count. Distillation reduces feature size.'
    e=make_evidence({'workId':'p','versionId':'v','contentHash':'h','accessLevel':'fulltext'},quote,quote,location={},obligation_ids=[])
    c={'claimId':'c','kind':'proposal','text':'建议先读剪枝，再读蒸馏。','conditions':{},'evidenceRefs':[e['evidenceId']]}
    return c,e


def verdict(purpose='reading_guidance',eid='E1'):
    return {'claimId':'c','status':'passed','reason':'次序与实际方法和阅读目标相符。',
        'adviceAudit':{'purpose':purpose,'targetPath':['text'],'appropriate':True,
        'premises':[{'evidenceId':eid,'path':['quote']}]}}


@pytest.mark.parametrize('revision',[False,True])
def test_advice_and_revisions_use_own_reviewer_and_citations(revision):
    c,e=fixture();before=deepcopy((c,e))
    invoke=Mock(return_value={'content':json.dumps([verdict()])})
    checker=BudgetedSemanticChecker(invoke,'r',general_advice_review=True,research_question='给出阅读顺序')
    result=checker.check_revisions([c],[e],[]) if revision else checker([c],[e])
    assert result[0]['status']=='passed'
    kw=invoke.call_args.kwargs
    assert kw['node']==('verify_repair_advice' if revision else 'verify_advice')
    assert 'NONEXPERIMENTAL recommendations' in kw['prompt'] and e['quote'] in kw['prompt']
    assert 'prospective experimental design' not in kw['prompt']
    assert result[0]['adviceAudit']['premises'][0]['evidenceId']==e['evidenceId']
    assert kw['use_reserve'] is True and (c,e)==before


@pytest.mark.parametrize('change',[
    lambda v:v.pop('adviceAudit'),
    lambda v:v['adviceAudit'].update(purpose='scientific_design'),
    lambda v:v['adviceAudit'].update(targetPath=['conditions']),
    lambda v:v['adviceAudit'].update(appropriate=False),
    lambda v:v['adviceAudit'].update(premises=[]),
    lambda v:v['adviceAudit']['premises'][0].update(evidenceId='foreign'),
    lambda v:v['adviceAudit']['premises'][0].update(path=['missing']),
])
def test_unbound_or_scientific_advice_audit_is_not_accepted(change):
    c,e=fixture();v=verdict();change(v)
    invoke=Mock(return_value={'content':json.dumps([v])})
    result=BudgetedSemanticChecker(invoke,'r',general_advice_review=True)([c],[e])
    assert result[0]['status']=='failed'


def test_old_policy_keeps_original_experiment_review_path():
    c,e=fixture();invoke=Mock(return_value={'content':json.dumps([{'claimId':'c','status':'passed','designAudit':{}}])})
    BudgetedSemanticChecker(invoke,'r')([c],[e])
    assert invoke.call_args.kwargs['node']=='verify_design_science'
    assert 'prospective experimental design' in invoke.call_args.kwargs['prompt']


@pytest.mark.parametrize('field',['designRole','executionSpec','designContractVersion','budgetContractVersion','hypothesisContractVersion','protocolContractVersion','workflowContractVersion'])
def test_formal_or_even_invalid_design_fields_cannot_select_advice_path(field):
    c,_=fixture();c[field]=None
    assert not eligible(c)


def test_hypotheses_and_experiment_objectives_keep_scientific_path():
    c,_=fixture();c['kind']='hypothesis';assert not eligible(c)
    assert not enabled({'recommendationReviewContractVersion':1,'state':{'outputKind':'experiment_design'}})
    assert enabled({'recommendationReviewContractVersion':1,'state':{'outputKind':'direction_survey'}})
    assert not enabled({'recommendationReviewContractVersion':True,'state':{'outputKind':'direction_survey'}})


def test_over_capacity_own_evidence_is_not_cut_or_dispatched():
    c,e=fixture();e['quote']='x'*25000;invoke=Mock()
    result=BudgetedSemanticChecker(invoke,'r',general_advice_review=True)([c],[e])
    assert result[0]['status']=='failed' and result[0]['executionState']=='not_started'
    invoke.assert_not_called()


def test_presentation_keeps_advice_clear_and_experiments_explicit_without_changing_claims():
    c,e=fixture();before=deepcopy((c,e))
    visible,folded=publication_notices([c],presentation_version=3,output_kind='direction_survey')
    payload={'claims':[c],'evidence':[e],'outputKind':'direction_survey','sections':[{'title':'推荐阅读顺序','claimIds':['c']}],
        'presentationVersion':3,'characterLimit':300,'limitations':visible,'verificationNotice':folded}
    body=render_report(payload);summary=conversation_summary([c],'complete',evidence=[e],output_kind='direction_survey',presentation_version=3)
    assert '实验建议' not in body+summary and '未经实验验证' not in body+summary
    assert '建议阅读顺序' not in body # preserve original wording, do not manufacture it
    assert c['text'] in body and c['text'] in summary and (c,e)==before
    old=render_report({**payload,'presentationVersion':2})
    assert '实验建议：' in old
    assert publication_notices([c],presentation_version=2)[0]
    assert publication_notices([c],presentation_version=3,output_kind='experiment_design')[0]
    assert visible_count({'claims':[c],'sections':payload['sections']},300,'direction_survey',[e],3)>len(c['text'])


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_advice_policy_is_server_owned_immutable_and_absent_on_legacy(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'给出阅读顺序','deferStart':True,
            'recommendationReviewContractVersion':replacement},start_async=False)
        assert run['recommendationReviewContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'recommendationReviewContractVersion':replacement})
        assert not enabled({'state':{'outputKind':'direction_survey'}})
    finally:facade.shutdown()


def test_advice_nodes_keep_json_capacity_and_finalization_registration():
    from services.deep_research.structured_output import ARRAY_NODES,DESIGN_REVIEW_NODES
    from services.deep_research.verification_capacity import has_verification_input_contract
    from services.deep_research.finalization_pool import _FINALIZATION_NODES
    for node in ('verify_advice','verify_repair_advice'):
        assert node in ARRAY_NODES and node not in DESIGN_REVIEW_NODES and node in _FINALIZATION_NODES
        assert has_verification_input_contract({'verificationInputContractVersion':1},node)
