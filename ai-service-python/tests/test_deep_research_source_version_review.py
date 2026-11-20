from copy import deepcopy
import json
import pytest
from services.deep_research.source_version_review import enabled,eligible,GUIDANCE
from test_deep_research_factual_decision import checker,target,evidence,response


@pytest.mark.parametrize('revision',[False,True])
@pytest.mark.parametrize('supported',[False,True])
def test_actual_checker_keeps_source_values_and_original_semantic_decision(revision,supported):
    sent=[];ev=evidence();ev[0].update(quote='Local coefficient \x0c means the new-sample weight.',
        sourceContext='Only the cited revision defines the convention.',
        sourceWorkId='work',sourceVersionId='work-v1',sourcePublicationIdentity={'revision':'v1'})
    original=deepcopy(ev)
    def invoke(**kwargs):sent.append(kwargs);return {'content':json.dumps([response(supported)])}
    c=checker(invoke,source_version_review=True)
    verdict=c.check_revisions([target()],ev,[]) if revision else c([target()],ev)
    assert verdict[0]['status']==('passed' if supported else 'failed')
    assert len(sent)==1 and sent[0]['node']==('verify_repair' if revision else 'verify')
    prompt=sent[0]['prompt'];assert prompt.count(GUIDANCE)==1
    assert '"versionId":"work-v1"' in prompt and '"revision":"v1"' in prompt
    assert '\\f' in prompt and ev==original
    assert 'Do not supply a replacement formula from memory' in prompt
    assert 'not the assertion that\nthe authors never proved a theorem' in prompt


@pytest.mark.parametrize('policy',[None,False,0,1,'1'])
def test_non_exact_direct_policy_keeps_legacy_request_exact(policy):
    sent=[]
    def invoke(**kwargs):sent.append(kwargs);return {'content':json.dumps([response()])}
    checker(invoke)([target()],evidence());baseline=sent.pop()
    checker(invoke,source_version_review=policy)([target()],evidence())
    assert sent[0]==baseline and GUIDANCE not in sent[0]['prompt']


def test_new_guidance_cannot_approve_foreign_premise_or_override_failed_boolean():
    for bad in ('foreign','negative'):
        raw=response(bad!='negative')
        if bad=='foreign':raw['scopeAudit']['premises'][0]['evidenceId']='other-version'
        raw['reason']='This should pass despite the invalid audit.'
        result=checker(lambda **_: {'content':json.dumps([raw])},source_version_review=True)([target()],evidence())
        assert result[0]['status']=='failed'


def test_proposals_do_not_inherit_factual_notation_guidance():
    assert not eligible([{**target(),'kind':'proposal'}])
    assert not eligible([{**target(),'designRole':'controls','executionSpec':{'x':1}}])
    sent=[]
    def invoke(**kwargs):sent.append(kwargs);return {'content':json.dumps([{'claimId':'c','status':'failed','reason':'Fixture unresolved design.'}])}
    checker(invoke,source_version_review=True)([{**target(),'kind':'proposal'}],evidence())
    assert sent and all(GUIDANCE not in x['prompt'] for x in sent)


@pytest.mark.parametrize('value',[None,True,False,0,2,1.0,'1'])
def test_exact_server_version_only(value):
    assert not enabled({'sourceVersionReviewContractVersion':value})
    assert enabled({'sourceVersionReviewContractVersion':1})


def test_server_policy_is_immutable_and_checker_resolves_each_runs_frozen_flag(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain','deferStart':True,
            'sourceVersionReviewContractVersion':False},start_async=False)
        assert enabled(r) and facade._make_semantic_checker(r['runId'])._source_version_review() is True
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(r['runId'],lambda r:{**r,'sourceVersionReviewContractVersion':False})
        old=deepcopy(r);old.pop('sourceVersionReviewContractVersion');old.update(runId='legacy',idempotencyKey='old');repo.create_run(old)
        assert facade._make_semantic_checker('legacy')._source_version_review() is False
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('legacy',lambda r:{**r,'sourceVersionReviewContractVersion':1})
    finally:facade.shutdown()
