"""Unreadable source windows cannot acquire literal evidence approval."""
from copy import deepcopy
from unittest.mock import Mock
import pytest
from services.deep_research.text_quality import guard
from services.deep_research.verification import make_evidence,verify_claims

SOURCE={'workId':'p','versionId':'v','contentHash':'h','accessLevel':'fulltext'}

def create(factory,quote,original=None):
    return factory(SOURCE,quote,quote if original is None else original,location={'page':1},obligation_ids=['o'])

@pytest.mark.parametrize('bad',['\x00','\x0c','\x18','\x7f','\ufffd'])
def test_preserves_raw_evidence_but_blocks_literal_approval_and_semantic_dispatch(bad):
    factory=guard(make_evidence,{'sourceGlyphContractVersion':1});quote='coefficient '+bad+' = 0.1'
    evidence=create(factory,quote)
    assert evidence['quote']==quote and evidence['sourceContext']==quote
    assert evidence['verification']['literal']=='failed' and evidence['textQualityAudit']['status']=='unreadable_glyphs'
    claim={'claimId':'c','kind':'reported','text':'The coefficient is0.1.','conditions':{},'evidenceRefs':[evidence['evidenceId']]}
    checker=Mock(side_effect=AssertionError('Unreadable source must not reach semantic approval'))
    result=verify_claims([claim],[evidence],checker)
    assert not result['accepted'] and result['rejected'][0]['reason']=='unverified_quotation'
    checker.assert_not_called()


def test_clean_quote_cannot_hide_unreadable_needed_context():
    ev=create(guard(make_evidence,{'sourceGlyphContractVersion':1}),'A result.','A result. Formula contains\x0c.')
    assert ev['verification']['literal']=='failed' and ev['quote']=='A result.'

@pytest.mark.parametrize('value',[None,True,False,0,2,1.0,'1'])
def test_legacy_and_noninteger_flags_leave_original_factory_and_result_exact(value):
    assert guard(make_evidence,{'sourceGlyphContractVersion':value}) is make_evidence
    assert create(guard(make_evidence,{}),'old\x0cquote')==create(make_evidence,'old\x0cquote')


def test_valid_unicode_math_and_linebreaks_keep_exact_evidence_schema():
    quote='α=0.1\nβ=0.001\tθ←θ−α\rvalue'
    assert create(guard(make_evidence,{'sourceGlyphContractVersion':1}),quote)==create(make_evidence,quote)


def test_facade_and_immutable_new_profile_keep_old_runs_unchanged(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    key='sourceGlyphContractVersion'
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Read','deferStart':True,key:False},start_async=False)
        assert type(r[key]) is int and r[key]==1
        assert create(facade._get_make_evidence(r['runId']),'bad\x0csource')['verification']['literal']=='failed'
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(r['runId'],lambda v:{**v,key:False})
        old=deepcopy(r);old.pop(key);old.update(runId='legacy',idempotencyKey='legacy');repo.create_run(old)
        assert create(facade._get_make_evidence('legacy'),'bad\x0csource')['verification']['literal']=='passed'
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('legacy',lambda v:{**v,key:1})
    finally:facade.shutdown()
