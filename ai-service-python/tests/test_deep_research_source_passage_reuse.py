from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.source_passages import extract,projection
from services.deep_research.source_passage_reuse import register,key
from services.deep_research.verification import make_evidence
from test_deep_research_source_passages import fixture
from test_deep_research_adaptive_extraction import activate


def setup(tmp_path,marked=True):
    repo,_,reads=fixture(tmp_path)
    if marked:repo=activate(repo,adaptiveExtractionContractVersion=3,sourcePassageReuseContractVersion=1)
    factory=Mock(wraps=make_evidence)
    extract(repo.require_run('r'),factory,lambda *_:True,repo.update_run)
    before=deepcopy(repo.require_run('r')['state']);factory.reset_mock()
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'plan':[{'itemId':'next','obligations':[
        {'obligationId':'new-goal','question':'A different question, still unverified',
         'requiredSources':['p0']}]}]}})
    return repo,factory,before,reads


@pytest.mark.parametrize('marked',[True,False])
def test_new_goal_can_reuse_only_literal_work_while_legacy_keeps_old_behavior(tmp_path,marked):
    repo,factory,before,_=setup(tmp_path,marked)
    extract(repo.require_run('r'),factory,lambda *_:True,repo.update_run)
    after=repo.require_run('r')['state']
    assert factory.call_count==(0 if marked else 1)
    assert [projection(e) for e in after['evidence']]==[projection(e) for e in before['evidence']]
    assert after['evidence'][0]['obligationIds']==['o','new-goal']
    assert all(e['verification']=={'literal':'passed','semantic':'unchecked'} for e in after['evidence'])
    assert len(after['sourcePassageExtraction']['entries'])==len(before['sourcePassageExtraction']['entries'])+1
    extract(repo.require_run('r'),factory,lambda *_:True,repo.update_run)
    assert repo.require_run('r')['state']==after


@pytest.mark.parametrize('mutation',['version','hash','context','title','owner','packet'])
def test_changed_input_or_source_metadata_requires_new_factory_work(tmp_path,mutation):
    repo,factory,_,_=setup(tmp_path)
    def change(r):
        source=r['state']['readResults'][0]
        if mutation=='version':source['versionId']='v2'
        elif mutation=='hash':source['contentHash']='changed'
        elif mutation=='context':source['pages'][0]['text']+=' A new literal source sentence.'
        elif mutation=='title':source['title']='Changed title'
        elif mutation=='owner':source['ownerMaterialId']='p0'
        else:
            # A different visible packet must not inherit the archived packet.
            source['pages'][0]['text']='Table row 1: Ours | 5'
            source['tableData']={'groups':[['Set',['Metric']]],'rows':[[1,'Ours',['5']]]}
        return r
    repo.update_run('r',change)
    try:extract(repo.require_run('r'),factory,lambda *_:True,repo.update_run)
    except DeepResearchError as exc:
        # Changed metadata for the same evidence ID is refused atomically.
        assert exc.code=='invalid_source_passage_state'
    assert factory.call_count>0


@pytest.mark.parametrize('revoke_at',[1,2])
def test_reuse_does_not_cache_permission_or_save_half_a_revoked_batch(tmp_path,revoke_at):
    repo,factory,_,_=setup(tmp_path);before=deepcopy(repo.require_run('r')['state'])
    class Scope:
        calls=0
        def validate_materials(self,*args):
            self.calls+=1;return self.calls!=revoke_at
    scope=Scope()
    with pytest.raises(DeepResearchError,match='材料范围'):
        extract(repo.require_run('r'),factory,scope,repo.update_run)
    assert repo.require_run('r')['state']==before
    factory.assert_not_called()


def test_ambiguous_archived_identity_is_never_chosen():
    first={'input':{'quote':'same','obligations':['old']},'evidenceId':'a','evidenceDigest':'x'}
    second={**deepcopy(first),'input':{'quote':'same','obligations':['new']},'evidenceId':'b'}
    index={};register(index,first);register(index,second);register(index,first)
    assert index[key(first['input'])] is None


def test_new_server_run_freezes_literal_reuse_policy(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.source_passage_reuse import enabled
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **kwargs:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'阅读论文',
                            'sourcePassageReuseContractVersion':1},start_async=False)
        assert enabled(repo.require_run(run['runId']))
        assert run['sourcePassageReuseContractVersion']==3
        for value in (True,2):
            with pytest.raises(ValueError,match='Immutable'):
                repo.update_run(run['runId'],lambda r:{**r,'sourcePassageReuseContractVersion':value})
    finally:facade.shutdown()


def rejected_setup(tmp_path,version=3):
    from services.deep_research.text_quality import guard
    repo,_,reads=fixture(tmp_path)
    repo=activate(repo,adaptiveExtractionContractVersion=3,sourcePassageReuseContractVersion=version,
                  sourceGlyphContractVersion=1)
    reads[0]['pages']=[{'text':'A damaged coefficient \x0c remains unreadable.'}]
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'readResults':reads}})
    factory=Mock(wraps=guard(make_evidence,repo.require_run('r')))
    extract(repo.require_run('r'),factory,lambda *_:True,repo.update_run)
    factory.reset_mock()
    return repo,factory,reads


def test_rejected_literal_is_cached_as_rejected_while_clean_incremental_work_continues(tmp_path):
    from services.deep_research.verification import verify_claims
    repo,factory,reads=rejected_setup(tmp_path)
    initial=deepcopy(repo.require_run('r')['state'])
    bad=next(e for e in initial['evidence'] if e['verification']['literal']=='failed')
    extract(repo.require_run('r'),factory,lambda *_:True,repo.update_run)
    factory.assert_not_called();assert repo.require_run('r')['state']==initial
    fresh=deepcopy(reads[1]);fresh.update(sourceId='fresh-source',contentHash='fresh-hash')
    fresh['pages']=[{'text':'A new clean observation under documented conditions.'}]
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'readResults':[reads[0],fresh]}})
    extract(repo.require_run('r'),factory,lambda *_:True,repo.update_run)
    assert factory.call_count==1
    saved=repo.require_run('r')['state'];assert next(e for e in saved['evidence'] if e['evidenceId']==bad['evidenceId'])==bad
    assert any(e['sourceId']=='fresh-source' and e['verification']['literal']=='passed' for e in saved['evidence'])
    semantic=Mock(side_effect=AssertionError('Rejected literal must never reach semantic approval'))
    result=verify_claims([{'claimId':'c','kind':'reported','text':'A supposed result.',
        'conditions':{},'evidenceRefs':[bad['evidenceId']]}],saved['evidence'],semantic)
    assert not result['accepted'] and result['rejected'][0]['reason']=='unverified_quotation'
    semantic.assert_not_called()


@pytest.mark.parametrize('mutation',['upgrade','remove_audit','change_count'])
def test_new_journal_binds_literal_rejection_and_its_reason_immutably(tmp_path,mutation):
    repo,factory,_=rejected_setup(tmp_path)
    def tamper(r):
        ev=next(e for e in r['state']['evidence'] if e['verification']['literal']=='failed')
        if mutation=='upgrade':ev['verification']['literal']='passed'
        elif mutation=='remove_audit':ev.pop('textQualityAudit')
        else:ev['textQualityAudit']['controlCount']=0
        return r
    repo.update_run('r',tamper);before=deepcopy(repo.require_run('r')['state'])
    with pytest.raises(DeepResearchError) as caught:extract(repo.require_run('r'),factory,lambda *_:True,repo.update_run)
    assert caught.value.code=='invalid_source_passage_state' and repo.require_run('r')['state']==before
    factory.assert_not_called()


def test_old_rejection_journal_is_not_reinterpreted_or_upgraded(tmp_path):
    repo,factory,_=rejected_setup(tmp_path,version=2)
    before=deepcopy(repo.require_run('r')['state'])
    with pytest.raises(DeepResearchError,match='来源身份不一致'):
        extract(repo.require_run('r'),factory,lambda *_:True,repo.update_run)
    assert repo.require_run('r')['state']==before
    factory.assert_not_called()


def test_new_journal_refuses_a_factory_that_skips_the_glyph_guard_atomically(tmp_path):
    repo,_,reads=fixture(tmp_path)
    repo=activate(repo,adaptiveExtractionContractVersion=3,sourcePassageReuseContractVersion=3,
                  sourceGlyphContractVersion=1)
    reads[1]['pages']=[{'text':'Unreadable coefficient \x0c must not become passed.'}]
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'readResults':reads}})
    before=deepcopy(repo.require_run('r')['state'])
    with pytest.raises(DeepResearchError,match='字符检查不一致'):
        extract(repo.require_run('r'),make_evidence,lambda *_:True,repo.update_run)
    assert repo.require_run('r')['state']==before
