from copy import deepcopy
from unittest.mock import Mock
import pytest
from services.deep_research.reporting import build_sections,render_report
from services.deep_research.graph import make_publish_node
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.facade import ResearchFacade


def test_accepted_revision_keeps_words_conditions_and_sources_under_neutral_scope_heading():
    claims=[{'claimId':'c','kind':'inference','text':'当前证据支持所测条件下的比较，不保证其他条件。',
             'conditions':{'dataset':'A'},'evidenceRefs':['e']}]
    proposed=[{'title':'未解决事项','claimIds':['c','unverified']}]
    before=deepcopy((claims,proposed))
    old=build_sections(claims,'claim_verification',proposed)
    new=build_sections(claims,'claim_verification',proposed,presentation_version=1)
    assert old==[{'title':'未解决事项','claimIds':['c']}]
    assert new==[{'title':'依据与范围','claimIds':['c']}]
    payload={'claims':claims,'sections':new,'gaps':[{'question':'仍需核对条件B'}]}
    text=render_report(payload)
    assert '## 依据与范围' in text and claims[0]['text'] in text and 'dataset：A' in text
    assert '还有 1 项未完成' in text and '仍需核对条件B' in text
    assert before==(claims,proposed)


@pytest.mark.parametrize('version',[0,True,'1',None,5])
def test_unversioned_presentation_is_unchanged(version):
    assert build_sections([{'claimId':'c'}],'claim_verification',
        [{'title':'未解决事项','claimIds':['c']}],presentation_version=version)[0]['title']=='未解决事项'


def test_publish_uses_frozen_presentation_without_changing_claims_or_model_calls():
    claim={'claimId':'c','kind':'inference','text':'有范围的判断','evidenceRefs':[]}
    record={'reportPresentationContractVersion':1,'state':{'outputKind':'claim_verification',
        'verifiedReport':{'verifiedClaims':[claim],'sections':[{'title':'未解决事项','claimIds':['c']}],
                          'answerCoverage':{'status':'checked','gaps':[]}},'plan':[]}}
    def update(_id,mutate,**kwargs):
        nonlocal record
        record=mutate(record);return record
    publish=Mock(return_value=({'publicationId':'p'},True))
    make_publish_node(publish,update)({'run_id':'r'})
    payload=publish.call_args.kwargs['payload']
    assert payload['claims']==[claim] and payload['sections']==[{'title':'依据与范围','claimIds':['c']}]
    assert '## 依据与范围' in publish.call_args.kwargs['report_text']


def test_client_cannot_disable_presentation_or_mutate_its_type(tmp_path):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'核对',
            'reportPresentationContractVersion':0,'deferStart':True},start_async=False)
        assert run['reportPresentationContractVersion']==4
        for value in [0,1,2,3,True,'4',None,5]:
            with pytest.raises(ValueError,match='Immutable'):
                repo.update_run(run['runId'],lambda r:{**r,'reportPresentationContractVersion':value})
    finally:
        facade.shutdown()
