from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.audience_single_source import enabled
from services.deep_research.audience_rewrite import _prepare,rewrite_for_beginner
from services.deep_research.contracts import DeepResearchError
from test_deep_research_audience_edit_budget import fixture,answer


def single():
    report,ev,q=fixture();report['claims']=report['claims'][:1]
    return report,ev,q


def test_single_source_prompt_omits_draft_prose_but_retains_sources_and_request():
    report,ev,q=single();before=deepcopy((report,ev))
    old,reason=_prepare(report,ev,q,contract_version=9);assert reason is None
    new,reason=_prepare(report,ev,q,contract_version=9,source_first_single=True)
    assert reason is None and report['claims'][0]['text'] in old['prompt']
    assert report['claims'][0]['text'] not in new['prompt'] and 'unverifiedPointHint' not in new['prompt']
    assert ev[0]['quote'] in new['prompt'] and q in new['prompt']
    assert new['outputTokens']==old['outputTokens']==3072 and len(new['prompt'].encode())<=24000
    assert (report,ev)==before


def test_received_edit_is_reused_and_cannot_change_protocol_on_resume():
    report,ev,q=single();states=[];invoke=Mock(return_value=answer())
    opts={'contract_version':9,'source_first_single':True}
    result=rewrite_for_beginner(report,ev,q,invoke,json.loads,checkpoint=states.append,**opts)
    assert result['claims'][0]['text']=='根据输入计算输出。'
    for key in ('claimId','kind','evidenceRefs','obligationIds','detailLevel','tableBindings'):
        assert result['claims'][0][key]==report['claims'][0][key]
    assert states[-1]['audienceSingleSourceContractVersion']==1
    invoke.reset_mock()
    assert rewrite_for_beginner(report,ev,q,invoke,json.loads,saved_state=states[-1],**opts)==result
    invoke.assert_not_called()
    for mutation in ('old','boolean','absent'):
        saved=deepcopy(states[-1]);kw=deepcopy(opts)
        if mutation=='old':kw.pop('source_first_single')
        elif mutation=='boolean':saved['audienceSingleSourceContractVersion']=True
        else:saved.pop('audienceSingleSourceContractVersion')
        with pytest.raises(DeepResearchError,match='保存'):rewrite_for_beginner(report,ev,q,invoke,json.loads,saved_state=saved,**kw)
    invoke.assert_not_called()


def test_multi_point_and_protected_targets_keep_original_route():
    report,ev,q=fixture();r={'audienceSingleSourceContractVersion':1,'audienceRewriteContractVersion':9}
    assert not enabled(r,report)
    with pytest.raises(ValueError):_prepare(report,ev,q,contract_version=9,source_first_single=True)
    report['claims']=report['claims'][:1]
    assert enabled(r,report) and not enabled(r,report,['edit'])
    with pytest.raises(ValueError):_prepare(report,ev,q,contract_version=9,source_first_single=True,protected_claim_ids=['edit'])
    for value in (None,True,False,'1',2):
        assert not enabled({**r,'audienceSingleSourceContractVersion':value},report)


def test_new_profile_cannot_be_supplied_or_added_to_legacy_task(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    key='audienceSingleSourceContractVersion'
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain','deferStart':True,key:False},start_async=False)
        assert type(r[key]) is int and r[key]==1
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(r['runId'],lambda r:{**r,key:False})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');old.pop(key);repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('old',lambda r:{**r,key:1})
    finally:facade.shutdown()
