import json
from copy import deepcopy
from unittest.mock import Mock
import pytest
from services.deep_research.repair import _prepare_repair,repair_rejected
from services.deep_research.general_advice import repair_enabled,repair_eligible,REPAIR_GUIDANCE
from services.deep_research.verification import make_evidence
from services.deep_research.contracts import DeepResearchError


def fixture():
    quote='Pruning reduces count; distillation reduces feature size.'
    ev=make_evidence({'workId':'p','versionId':'v','contentHash':'h','accessLevel':'fulltext'},quote,quote,location={},obligation_ids=['o'])
    claims=[{'claimId':'c1','kind':'reported','text':'剪枝减少数量。','evidenceRefs':[ev['evidenceId']],'obligationIds':['o']},
        {'claimId':'c2','kind':'proposal','text':'先读摘要（E99）然后看方法。','evidenceRefs':[ev['evidenceId']],'obligationIds':['o']}]
    checks={'accepted':[],'rejected':[{'claimId':'c2','reason':'internal_reference_in_prose'}]}
    options={'fact_redraft':True,'source_aware_redraft':True,'concise_factual':True,'compact_source_repair':True}
    return {'claims':claims},checks,[ev],options


def test_reading_repair_rebuilds_without_failed_prose_or_experiment_settings():
    report,checks,evidence,options=fixture();before=deepcopy((report,checks,evidence))
    old=_prepare_repair(report,checks,evidence,'说明方法并给出阅读顺序，300字以内',**options)
    new=_prepare_repair(report,checks,evidence,'说明方法并给出阅读顺序，300字以内',ordinary_advice=True,**options)
    assert 'For existing proposals, choose concrete seed/split/level/budget/confidence settings' in old['prompt']
    assert 'For existing proposals, choose concrete seed/split/level/budget/confidence settings' not in new['prompt']
    assert REPAIR_GUIDANCE in new['prompt'] and report['claims'][1]['text'] not in new['prompt']
    assert evidence[0]['quote'] in new['prompt']
    assert old['allowed']==new['allowed'] and new['originals']==old['originals']
    assert (report,checks,evidence)==before


@pytest.mark.parametrize('field',['designRole','executionSpec','designContractVersion','protocolContractVersion','workflowContractVersion'])
def test_formal_or_invalid_experimental_metadata_cannot_enter_reading_repair(field):
    report,checks,evidence,options=fixture();report['claims'][1][field]=None
    assert not repair_eligible(report)
    with pytest.raises(ValueError):_prepare_repair(report,checks,evidence,'给出阅读顺序',ordinary_advice=True,**options)


def test_scientific_hypothesis_or_goal_keeps_existing_path():
    report,checks,evidence,options=fixture();report['claims'][1]['kind']='hypothesis'
    assert not repair_eligible(report)
    assert not repair_enabled({'recommendationReviewContractVersion':1,'recommendationRepairContractVersion':1,
        'state':{'outputKind':'experiment_design'}})
    assert not repair_enabled({'recommendationReviewContractVersion':1,'state':{'outputKind':'direction_survey'}})


def test_new_advice_policy_cannot_reuse_old_repair_batch():
    report,checks,evidence,options=fixture();states=[]
    invoke=Mock(return_value={'content':'[]'})
    repair_rejected(report,checks,evidence,'说明方法和阅读顺序',invoke,json.loads,checkpoint=lambda s:states.append(deepcopy(s)),**options)
    assert states and invoke.call_count==1
    invoke.reset_mock()
    with pytest.raises(DeepResearchError,match='保存的修订计划'):
        repair_rejected(report,checks,evidence,'说明方法和阅读顺序',invoke,json.loads,batch_state=states[-1],ordinary_advice=True,**options)
    invoke.assert_not_called()


def test_model_cannot_promote_advice_to_a_reported_fact():
    report,checks,evidence,options=fixture()
    invoke=Mock(return_value={'content':json.dumps([{'claimId':'c2','kind':'reported',
        'text':'作者要求这个阅读顺序。','evidenceRefs':['E1'],'conditions':{},'detailLevel':'fulltext'}])})
    result=repair_rejected(report,checks,evidence,'给出阅读顺序',invoke,json.loads,ordinary_advice=True,**options)
    assert result==[]


@pytest.mark.parametrize('replacement',[None,True,0,2,'1'])
def test_advice_repair_marker_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'给出阅读顺序','deferStart':True,
            'recommendationRepairContractVersion':replacement},start_async=False)
        assert run['recommendationRepairContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'recommendationRepairContractVersion':replacement})
    finally:facade.shutdown()
