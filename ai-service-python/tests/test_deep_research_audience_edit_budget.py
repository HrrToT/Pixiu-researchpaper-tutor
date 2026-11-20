from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.audience_edit_budget import allocation,enabled
from services.deep_research.audience_rewrite import _prepare,_merge,rewrite_for_beginner
from services.deep_research.contracts import DeepResearchError
from test_deep_research_authored_body import evidence


def fixture():
    report={'sections':[],'claims':[
        {'claimId':'edit','kind':'reported','text':'原来很长的说明。'*30,'conditions':{},'evidenceRefs':['a'],'obligationIds':['o'],'detailLevel':'fulltext','tableBindings':[]},
        {'claimId':'fixed','kind':'inference','text':'仅讨论当前证据中的设置，不代表所有情形。','conditions':{},'evidenceRefs':['b'],'obligationIds':['o'],'detailLevel':'fulltext',
         'tableBindings':[],'scopeExpression':{'observedSettings':[],'notEstablished':[{'type':'comparison_evidence','subjects':['A','B'],'quantity':'质量'}]}}]}
    return report,evidence(),'给新手解释，限100字。'


def answer(text='根据输入计算输出。',extra=None):
    rows=[{'claimId':'edit','text':text,'conditions':{}}]
    if extra:rows.append(extra)
    return {'content':json.dumps({'claims':rows},ensure_ascii=False),'finishReason':'stop'}


def options():return dict(contract_version=9,protected_claim_ids=['fixed'],protected_edits=True)


def test_prompt_deducts_fixed_content_and_only_editable_targets_have_output_permission():
    report,ev,q=fixture();before=deepcopy((report,ev))
    b=allocation(report,q,['fixed']);assert b['editableCharacters']==100-b['fixedCharacters']
    request,reason=_prepare(report,ev,q,**options());assert reason is None
    prompt=request['prompt'];assert f"fit {b['editableCharacters']} characters" in prompt
    target=json.JSONDecoder().raw_decode(prompt.split('Target IDs, original kinds and source permissions (metadata, NOT scientific approval):\n')[1])[0]
    assert [t['claimId'] for t in target]==['edit']
    assert 'Return ONLY\neditableClaimIds' in prompt and 'Fixed answer context' in prompt
    assert ev[0]['quote'] in prompt and len(prompt.encode())<=24000
    assert (report,ev)==before


def test_server_merges_complete_fixed_object_and_received_response_is_reused():
    report,ev,q=fixture();original=deepcopy(report);states=[];invoke=Mock(return_value=answer())
    result=rewrite_for_beginner(report,ev,q,invoke,json.loads,checkpoint=states.append,**options())
    assert result['claims'][1]==original['claims'][1] and result['claims'][0]['text']=='根据输入计算输出。'
    for key in ('claimId','kind','evidenceRefs','obligationIds','detailLevel','tableBindings'):
        assert result['claims'][0][key]==original['claims'][0][key]
    assert states[0]['status']=='pending' and states[0]['editBudget']==allocation(report,q,['fixed'])
    invoke.assert_called_once();invoke.reset_mock()
    assert rewrite_for_beginner(report,ev,q,invoke,json.loads,saved_state=states[-1],**options())==result
    invoke.assert_not_called();assert report==original
    from services.deep_research.verification import verify_claims
    checker=Mock(return_value=[{'claimId':c['claimId'],'status':'failed','reason':'Unverified fixture'} for c in result['claims']])
    assert not verify_claims(result['claims'],ev,checker)['accepted']


@pytest.mark.parametrize('bad',['fixed','foreign','duplicate','missing','extra_key','overlength'])
def test_output_cannot_change_fixed_objects_expand_targets_or_exceed_full_budget(bad):
    report,ev,q=fixture();raw=json.loads(answer()['content']);b=allocation(report,q,['fixed'])
    if bad=='fixed':raw['claims'].append({'claimId':'fixed','text':'改成新范围。','conditions':{}})
    elif bad=='foreign':raw['claims'][0]['claimId']='other'
    elif bad=='duplicate':raw['claims'].append(deepcopy(raw['claims'][0]))
    elif bad=='missing':raw['claims']=[]
    elif bad=='extra_key':raw['claims'][0]['evidenceRefs']=['b']
    elif bad=='overlength':raw['claims'][0]['text']='长'*(b['editableCharacters']+1)
    before=deepcopy(report);reasons=[]
    assert _merge(report,json.dumps(raw),json.loads,q,rejection=reasons.append,**options()) is None
    assert reasons and report==before
    if bad=='overlength':assert reasons==['character_limit']


def test_duplication_of_fixed_contribution_is_still_rejected():
    report,ev,q=fixture();reasons=[]
    assert _merge(report,answer(report['claims'][1]['text'])['content'],json.loads,q,rejection=reasons.append,**options()) is None
    assert reasons==['collapsed_distinct_points']


def test_table_subset_permission_applies_only_to_editable_targets():
    report,ev,q=fixture()
    report['claims'][0]['tableBindings']=[{'evidenceId':'a','rowNumber':1,'groupIndex':0,'metric':'M','value':'12'}]
    report['claims'][1]['tableBindings']=[{'evidenceId':'b','rowNumber':2,'groupIndex':0,'metric':'M','value':'20'}]
    raw=json.loads(answer()['content']);raw['claims'][0]['retainedTableBindingIndexes']=[]
    result=_merge(report,json.dumps(raw),json.loads,q,**options())
    assert result['claims'][0]['tableBindings']==[] and result['claims'][1]==report['claims'][1]
    raw['claims'][0]['retainedTableBindingIndexes']=[1]
    assert _merge(report,json.dumps(raw),json.loads,q,**options()) is None


def test_editable_and_fixed_conditions_both_count_toward_shared_limit():
    report,ev,q=fixture();report['claims'][1]['conditions']={'设备':'A100'}
    raw=json.loads(answer()['content']);raw['claims'][0]['conditions']={'补充':'长'*100}
    reasons=[]
    assert _merge(report,json.dumps(raw),json.loads,q,rejection=reasons.append,**options()) is None
    assert reasons==['character_limit']


@pytest.mark.parametrize('mutation',['protocol','budget','policy'])
def test_saved_request_cannot_switch_or_tamper_with_frozen_edit_budget(mutation):
    report,ev,q=fixture();states=[]
    rewrite_for_beginner(report,ev,q,Mock(return_value=answer()),json.loads,checkpoint=states.append,**options())
    saved=deepcopy(states[-1]);opts=options()
    if mutation=='protocol':saved['audienceBudgetContractVersion']=True
    elif mutation=='budget':saved['editBudget']['editableCharacters']+=1
    else:opts['protected_edits']=False
    invoke=Mock()
    with pytest.raises(DeepResearchError):rewrite_for_beginner(report,ev,q,invoke,json.loads,saved_state=saved,**opts)
    invoke.assert_not_called()


@pytest.mark.parametrize('mode',['all_fixed','fixed_exhausts_limit'])
def test_uneditable_request_skips_before_dispatch_without_altering_source(mode):
    report,ev,q=fixture();opts=options()
    if mode=='all_fixed':opts['protected_claim_ids']=['edit','fixed']
    else:report['claims'][1]['text']='长'*101
    before=deepcopy(report);invoke=Mock();states=[]
    assert rewrite_for_beginner(report,ev,q,invoke,json.loads,checkpoint=states.append,**opts)==before
    invoke.assert_not_called();assert states[-1]['status']=='skipped'


@pytest.mark.parametrize('value',[None,True,False,0,2,1.0,'1'])
def test_only_exact_frozen_policy_enables_budget(value):
    r={'question':'给新手解释，限100字。','audienceRewriteContractVersion':9,'audienceBudgetContractVersion':value}
    assert not enabled(r)
    r['audienceBudgetContractVersion']=1;assert enabled(r)


def test_unknown_response_retains_exact_pending_request_and_cannot_downgrade_protocol():
    report,ev,q=fixture();states=[]
    def unknown(*_):raise OSError('Unknown response')
    with pytest.raises(OSError):rewrite_for_beginner(report,ev,q,unknown,json.loads,checkpoint=states.append,**options())
    assert states[-1]['status']=='pending' and states[-1]['editBudget']==allocation(report,q,['fixed'])
    opts=options();opts['protected_edits']=False;invoke=Mock()
    with pytest.raises(DeepResearchError):rewrite_for_beginner(report,ev,q,invoke,json.loads,saved_state=states[-1],**opts)
    invoke.assert_not_called()


def test_plain_compaction_keeps_cap_and_legacy_profile_but_disables_reasoning_for_new_runs():
    from services.deep_research.factual_reasoning import compaction_options
    from services.deep_research.runtime import research_model_options
    r={'factualReasoningContractVersion':10};q='解释，限300字。'
    legacy=research_model_options('synthesize_compact',{'max_tokens':2000,**compaction_options(r,q,'claim_verification')})
    new=research_model_options('synthesize_compact',{'max_tokens':2000,**compaction_options({**r,'plainCompactionContractVersion':1},q,'claim_verification')})
    assert legacy['thinking']=={'type':'enabled'} and legacy['reasoning_effort']=='low'
    assert new['thinking']=={'type':'disabled'} and new['reasoning_effort']=='none'
    assert legacy['max_tokens']==new['max_tokens']==8192
    for bad in (True,False,0,2,None,'1'):
        assert compaction_options({**r,'plainCompactionContractVersion':bad},q,'claim_verification')==compaction_options(r,q,'claim_verification')


def test_both_server_owned_fields_are_immutable_and_absent_from_legacy_runs(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    fields=['audienceBudgetContractVersion','plainCompactionContractVersion']
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'解释','deferStart':True,**dict.fromkeys(fields,False)},start_async=False)
        assert all(type(r[k]) is int and r[k]==1 for k in fields)
        for key in fields:
            with pytest.raises(ValueError,match='Immutable'):repo.update_run(r['runId'],lambda r:{**r,key:False})
        old=deepcopy(r);old.update(runId='legacy',idempotencyKey='old')
        for key in fields:old.pop(key)
        repo.create_run(old)
        for key in fields:
            with pytest.raises(ValueError,match='Immutable'):repo.update_run('legacy',lambda r:{**r,key:1})
    finally:facade.shutdown()
