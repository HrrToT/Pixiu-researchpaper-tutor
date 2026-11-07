from copy import deepcopy
import pytest
from services.deep_research.audience_request import described_reader_request,enabled
from services.deep_research.audience_rewrite import eligible
from test_deep_research_audience_rewrite import fixture


def record(question):
    return {'question':question,'audienceRewriteContractVersion':9,'audienceRequestContractVersion':1}


@pytest.mark.parametrize('question',[
    '面向了解梯度下降但没读过这篇论文的人，解释方法和适用范围。',
    '给没接触过这个领域的同学讲解方法。',
    '请向尚不熟悉这项方法的读者说明推导思路。',
    '面向只了解基本概念的读者介绍论文。',
    "Explain this method to readers familiar with calculus who haven't read this paper.",
    'Explain for students who are new to this research area.',
])
def test_described_background_is_admitted_only_with_frozen_new_policy(question):
    report,_=fixture();r=record(question)
    assert described_reader_request(question) and eligible(r,report,'claim_verification')
    old=deepcopy(r);old.pop('audienceRequestContractVersion')
    assert not eligible(old,report,'claim_verification')


@pytest.mark.parametrize('question',[
    '解释论文的方法。','详细推导这篇论文。','列出没读过这篇论文的人。',
    '面向精通此领域的读者解释方法。','面向没读过论文的专家介绍研究前沿。',
    '分析“面向没读过论文的人”这一用语。',
    'Explain this for expert readers who have not read this paper.',
])
def test_ordinary_metalinguistic_or_expert_requests_do_not_infer_novice_ability(question):
    report,_=fixture();assert not eligible(record(question),report,'claim_verification')


@pytest.mark.parametrize('prefix',['无需通俗化，','不要简化，','不用面向新手，'])
def test_explicit_negative_wins_in_same_human_layer(prefix):
    report,_=fixture();assert not eligible(record(prefix+'面向没读过这篇论文的人解释。'),report,'claim_verification')


def test_latest_human_clarification_wins_and_evidence_cannot_create_audience_request():
    report,_=fixture();q='面向没读过这篇论文的人解释。'
    r=record(q);r.update(clarificationContractVersion=1,state={'clarification':'无需简化，保留技术推导'})
    assert not eligible(r,report,'claim_verification')
    r=record('无需简化，保留技术推导');r.update(clarificationContractVersion=1,state={'clarification':q})
    assert eligible(r,report,'claim_verification')
    r=record('解释方法');r['state']={'evidence':[{'quote':q}],'plan':[{'question':q}]}
    assert not eligible(r,report,'claim_verification')


@pytest.mark.parametrize('flag',[None,True,False,0,2,1.0,'1'])
def test_only_exact_server_flag_can_expand_admission(flag):
    report,_=fixture();r=record('面向没读过论文的人解释。');r['audienceRequestContractVersion']=flag
    assert not enabled(r) and not eligible(r,report,'claim_verification')


def test_expansion_keeps_output_and_claim_kind_guards():
    report,_=fixture();r=record('面向没读过论文的人解释。')
    assert not eligible(r,report,'experiment_design')
    report['claims'][0].update(kind='proposal',executionSpec={'parameters':[]})
    assert not eligible(r,report,'claim_verification')


def test_server_owns_immutable_flag_and_does_not_upgrade_old_runs(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain','deferStart':True,
            'audienceRequestContractVersion':False},start_async=False)
        assert enabled(r)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(r['runId'],lambda r:{**r,'audienceRequestContractVersion':False})
        old=deepcopy(r);old.pop('audienceRequestContractVersion');old.update(runId='legacy',idempotencyKey='old')
        repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('legacy',lambda r:{**r,'audienceRequestContractVersion':1})
        assert not enabled(repo.require_run('legacy'))
    finally:facade.shutdown()
