from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.verification import make_evidence,verify_claims

WORK='arxiv:2406.01467'


def inputs(versions):
    evidence=[]
    for version in versions:
        quote='The method penalizes local differences.'
        evidence.append(make_evidence({'workId':WORK,'versionId':WORK+version,'contentHash':version,'accessLevel':'fulltext'},
            quote,quote,location={'page':1},obligation_ids=['o']))
    claim={'claimId':'c','text':'该方法惩罚局部差异。','kind':'reported','evidenceRefs':[e['evidenceId'] for e in evidence],
           'conditions':{},'obligationIds':['o'],'detailLevel':'fulltext'}
    return claim,evidence


@pytest.mark.parametrize('kind',['reported','inference','proposal'])
@pytest.mark.parametrize('versions',[['v2'],['v1','v2']])
def test_other_revision_cannot_be_approved_or_hidden_by_a_kind_change(kind,versions):
    claim,evidence=inputs(versions);claim['kind']=kind;before=deepcopy((claim,evidence));semantic=Mock()
    result=verify_claims([claim],evidence,semantic,requested_source_revisions={WORK:[WORK+'v1']})
    assert not result['accepted'] and result['rejected'][0]['reason']=='requested_version_mismatch'
    semantic.assert_not_called();assert (claim,evidence)==before


def test_explicitly_requested_two_revisions_still_need_independent_support():
    claim,evidence=inputs(['v1','v3']);semantic=Mock(return_value=[{'claimId':'c','status':'failed','reason':'No scientific approval from matching identity'}])
    result=verify_claims([claim],evidence,semantic,requested_source_revisions={WORK:[WORK+'v1',WORK+'v3']})
    assert not result['accepted'] and result['rejected'][0]['reason']=='semantic_unresolved'
    semantic.assert_called_once()


@pytest.mark.parametrize('constraints',[[],{'paper':['arxiv:2406.01467v1']},{WORK:[WORK]}, {WORK:['arxiv:2308.04079v1']}])
def test_malformed_server_constraints_fail_before_any_semantic_call(constraints):
    claim,evidence=inputs(['v1']);semantic=Mock()
    with pytest.raises(ValueError):verify_claims([claim],evidence,semantic,requested_source_revisions=constraints)
    semantic.assert_not_called()


@pytest.mark.parametrize('policy',[1,2])
def test_facade_binds_the_frozen_question_and_keeps_original_runs_unchanged(tmp_path,policy):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t','question':'Read arxiv:2406.01467v1','exactDiscoveryContractVersion':policy,
                     'sourcePolicy':{'mode':'external_only'}})
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object());before=repo.require_run('r')
    claim,evidence=inputs(['v2']);semantic=Mock(return_value=[{'claimId':'c','status':'passed'}])
    try:
        result=facade._get_verify_claims('r')([claim],evidence,semantic)
        if policy==2:
            assert result['rejected'][0]['reason']=='requested_version_mismatch';semantic.assert_not_called()
        else:assert result['accepted'];semantic.assert_called_once()
        assert repo.require_run('r')==before
    finally:facade.shutdown()
