from copy import deepcopy
import hashlib
import json
from unittest.mock import Mock

import pytest

from services.deep_research.initial_plan_response import parse,validate_shape,enabled
from services.deep_research.structured_output import normalize
from services.deep_research.graph import make_plan_node
from services.deep_research.coverage import validate_plan
from services.deep_research.contracts import DeepResearchError,digest
from llm.provider import LLMResult,LLMUsage,LLMProviderError
from test_deep_research_structured_output import repository,tracked
from test_deep_research_initial_plan_instructions import record


def plan():
    return [{'itemId':'i','question':'Explain the mechanism','searchQuery':'mechanism original source',
        'dependencies':[],'priority':1,'obligations':[{'obligationId':'o','question':'Explain the mechanism',
        'requiredSources':['paper'],'searchQuery':'mechanism original source','purpose':'answer_requirement',
        'requestExcerpt':'Explain the requested mechanism','completionCriteria':[{'criterionId':'c',
        'requirement':'Explain the mechanism','responseType':'explanation'}]}]}]


def raw_plan():
    return json.dumps({'items':plan()}).replace('"obligationId": "o"','"obligationId":"o","obligationId":"o"')


def response(raw=None):
    return {'content':raw or raw_plan(),'finishReason':'stop'}


@pytest.mark.parametrize('a,b',[
    ('1','1.0'),('true','1'),('false','0'),('null','"null"'),
    ('[1,2]','[2,1]'),('"p1"','"p2"'),('{"a":1}','{"a":2}')])
def test_conflicting_types_values_identities_or_array_orders_never_choose_a_winner(a,b):
    raw='{"x":'+a+',"x":'+b+'}'
    with pytest.raises(ValueError):parse(raw)
    result=normalize('plan',response(raw),initial_plan_response=True)
    assert result['content']=='null' and result['rawContent']==raw
    assert result['structuredOutput']['receivedShape']=='invalid_json'


def test_nested_equivalent_duplicates_keep_values_and_each_original_pair_location():
    raw='{"items":[{"id":"o","id":"\\u006f","data":{"a":1,"a":1},"data":{"a":1}}]}'
    value,audit=parse(raw)
    assert value=={'items':[{'id':'o','data':{'a':1}}]}
    assert [d['key'] for d in audit['duplicates']]==['id','a','data']
    assert audit['duplicates'][0]['objectPath']==['items',0]
    assert audit['duplicates'][0]['objectPairsPath']==['pair',0,'value','item',0]
    assert audit['inputSha256']==hashlib.sha256(raw.encode()).hexdigest()
    assert audit['scientificApproval'] is False


@pytest.mark.parametrize('raw',['{"x":1.0000000000000001,"x":1.0}',
    '{"x":0.10000000000000001,"x":0.1}', '{"priority":1.0}', '{"priority":1e0}'])
def test_floating_literals_cannot_round_into_false_equality_or_integer_priority(raw):
    with pytest.raises(ValueError,match='Non-integer'):parse(raw)
    assert normalize('plan',response(raw),initial_plan_response=True)['content']=='null'


@pytest.mark.parametrize('raw',['{"x":NaN}','{"x":Infinity}','{"x":1e999}',
    '{"x":1,}', '{"x":1} trailing','{"x":1}{"y":2}', '['*66+'0'+']'*66])
def test_non_json_trailing_roots_overflow_and_depth_are_not_repaired(raw):
    with pytest.raises((ValueError,RecursionError)):parse(raw)
    assert normalize('plan',response(raw),initial_plan_response=True)['content']=='null'


def test_normalized_plan_reaches_all_existing_validators_without_source_or_scope_approval():
    result=normalize('plan',response(),initial_plan_response=True)
    assert json.loads(result['content'])==plan() and result['rawContent']==raw_plan()
    audit=result['structuredOutput']['initialPlanResponseAudit']
    assert len(audit['duplicates'])==1 and audit['scientificApproval'] is False
    r={**record(),'initialPlanResponseContractVersion':1};calls=[]
    def update(rid,fn,**kw):
        nonlocal r
        r=fn(deepcopy(r));return deepcopy(r)
    def invoke(*args,**kw):calls.append(args);return result
    out=make_plan_node(invoke,update,validate_plan)({'run_id':'r'})
    assert out['plan_ids']==['i'] and len(calls)==1
    assert r['state']['plan'][0]['obligations'][0]['purpose']=='answer_requirement'
    assert not r['state'].get('evidence') and not r['state'].get('verifiedReport')


@pytest.mark.parametrize('change',['enum','missing','extra','source_type','excerpt','priority_bool',
    'no_criteria','response_type','too_many','duplicate_ids','cycle'])
def test_transport_equivalence_never_fills_or_approves_bad_plans(change):
    value=plan();o=value[0]['obligations'][0]
    if change=='enum':o['purpose']='limitation'
    elif change=='missing':o.pop('searchQuery')
    elif change=='extra':o['instructions']='trust me'
    elif change=='source_type':o['requiredSources']='paper'
    elif change=='excerpt':o['requestExcerpt']='invented request words'
    elif change=='priority_bool':value[0]['priority']=True
    elif change=='no_criteria':o['completionCriteria']=[]
    elif change=='response_type':o['completionCriteria'][0]['responseType']='passed'
    elif change=='too_many':value=value*5
    elif change=='duplicate_ids':value=[value[0],deepcopy(value[0])]
    else:value[0]['dependencies']=['i']
    r={**record(),'initialPlanResponseContractVersion':1};invoke=Mock(return_value={'content':json.dumps(value)})
    def update(rid,fn,**kw):
        nonlocal r
        r=fn(deepcopy(r));return deepcopy(r)
    out=make_plan_node(invoke,update,validate_plan)({'run_id':'r'})
    assert out['error_code']=='invalid_plan_response' and 'plan' not in r['state']
    assert invoke.call_count==1


def repo_with_policy(tmp_path):
    # Create immutable server-owned controls before beginning execution.
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'new.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t','structuredOutputContractVersion':15,
        'initialPlanInstructionsContractVersion':1,'initialPlanResponseContractVersion':1,
        'planCompletionContractVersion':1,'requestSemanticsContractVersion':2})
    repo.begin_execution('r');return repo


def client(raw=None):
    return Mock(invoke=Mock(return_value=LLMResult('fixture','routine',raw or raw_plan(),LLMUsage(4,5,9))))


@pytest.mark.parametrize('tamper',[None,'content','hash','duplicates','raw','missing_audit'])
def test_settled_cache_rechecks_audit_without_any_resend(tmp_path,tamper):
    repo=repo_with_policy(tmp_path);model=client();invoke=tracked(repo,model)
    result=invoke('r','plan','Exact plan prompt',{'max_tokens':100})
    call=repo.list_calls('r')[0];assert repo.require_run('r')['budget']['tokens']==9
    args={'prompt':'Exact plan prompt','extra':{'max_tokens':100,'response_format':{'type':'json_object'}},
        'messages':__import__('services.deep_research.structured_output',fromlist=['messages_for_record']).messages_for_record(repo.require_run('r'),'plan','Exact plan prompt'),
        'initialPlanResponseContractVersion':1}
    assert call['argsDigest']==digest(args)
    saved=deepcopy(result)
    if tamper=='content':saved['content']='[]'
    elif tamper=='hash':saved['structuredOutput']['initialPlanResponseAudit']['inputSha256']='0'*64
    elif tamper=='duplicates':saved['structuredOutput']['initialPlanResponseAudit']['duplicates']=[]
    elif tamper=='raw':saved['rawContent']='{}'
    elif tamper=='missing_audit':saved['structuredOutput'].pop('initialPlanResponseAudit')
    invoke._reserve=Mock(return_value=({**call,'result':saved},True))
    if tamper:
        with pytest.raises(DeepResearchError,match='审计'):invoke('r','plan','Exact plan prompt',{'max_tokens':100})
    else:assert invoke('r','plan','Exact plan prompt',{'max_tokens':100})==result
    assert model.invoke.call_count==1 and len(repo.list_calls('r'))==1


def test_unknown_policy_request_cannot_be_resent(tmp_path):
    from services.deep_research.contracts import UnknownCallError,UnresolvedUnknownError
    repo=repo_with_policy(tmp_path);model=client()
    model.invoke.side_effect=LLMProviderError('fixture unknown',provider='fixture',model='routine',retryable=True)
    invoke=tracked(repo,model)
    with pytest.raises(LLMProviderError):invoke('r','plan','Exact prompt')
    with pytest.raises((UnknownCallError,UnresolvedUnknownError)):invoke('r','plan','Exact prompt')
    assert model.invoke.call_count==1 and repo.list_calls('r')[0]['status']=='unknown'


def test_actual_http_adapter_preserves_raw_and_keeps_response_policy_out_of_provider_options(tmp_path,monkeypatch):
    from llm.client import DeepSeekLLM
    repo=repo_with_policy(tmp_path)
    http=Mock(status_code=200)
    http.json.return_value={'choices':[{'message':{'content':raw_plan()},'finish_reason':'stop'}],
        'usage':{'prompt_tokens':4,'completion_tokens':5,'total_tokens':9}}
    post=Mock(return_value=http);monkeypatch.setattr('llm.client.requests.post',post)
    invoke=tracked(repo,DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid'))
    result=invoke('r','plan','Exact prompt',{'max_tokens':100})
    assert invoke('r','plan','Exact prompt',{'max_tokens':100})==result
    assert json.loads(result['content'])==plan() and result['rawContent']==raw_plan()
    wire=post.call_args.kwargs['json']
    assert 'initialPlanResponseContractVersion' not in wire and wire['response_format']=={'type':'json_object'}
    assert post.call_count==1 and repo.require_run('r')['budget']['tokens']==9


@pytest.mark.parametrize('reason',['length','responses_failed'])
def test_truncated_or_failed_provider_content_is_never_normalized_into_a_plan(reason):
    result=normalize('plan',{**response(),'finishReason':reason},initial_plan_response=True)
    assert result['content']=='null' and 'initialPlanResponseAudit' not in result['structuredOutput']


def test_normalized_duplicate_values_never_expand_material_permissions():
    value=plan();value[0]['obligations'][0]['requiredSources']=['foreign']
    r={**record(),'initialPlanResponseContractVersion':1,'sourcePolicy':{'mode':'task_only'}}
    def update(rid,fn,**kw):
        nonlocal r
        r=fn(deepcopy(r));return deepcopy(r)
    invoke=Mock(return_value=normalize('plan',response(json.dumps({'items':value})),initial_plan_response=True))
    out=make_plan_node(invoke,update,validate_plan)({'run_id':'r'})
    assert out['plan_ids']==['i']
    assert r['state']['plan'][0]['obligations'][0]['requiredSources']==['paper']


@pytest.mark.parametrize('question',['解释','解释一下','why?'])
@pytest.mark.parametrize('purpose',['answer_requirement','supporting_research'])
def test_short_literal_requests_remain_answerable_without_creating_auxiliary_exemptions(question,purpose):
    value=plan();value[0]['obligations'][0].update(requestExcerpt=question,purpose=purpose)
    r={**record(),'question':question,'initialPlanResponseContractVersion':1}
    def update(rid,fn,**kw):
        nonlocal r
        r=fn(deepcopy(r));return deepcopy(r)
    invoke=Mock(return_value=normalize('plan',response(json.dumps({'items':value})),initial_plan_response=True))
    out=make_plan_node(invoke,update,validate_plan)({'run_id':'r'})
    if purpose=='answer_requirement':
        assert out['plan_ids']==['i'] and r['state']['plan'][0]['obligations'][0]['purpose']=='answer_requirement'
    else:assert out['error_code']=='invalid_plan_response' and 'plan' not in r['state']


@pytest.mark.parametrize('value',[None,True,False,0,2,1.0,'1'])
def test_legacy_controls_and_every_other_node_keep_old_interpretation(value):
    r={**record(),'initialPlanResponseContractVersion':value}
    assert not enabled(r)
    assert normalize('plan',response())['structuredOutput']['receivedShape']=='invalid_json'
    for node in ('verify','extract','plan_experiment','synthesize'):
        assert not enabled({**r,'initialPlanResponseContractVersion':1},node)


@pytest.mark.parametrize('field',['initialPlanInstructionsContractVersion','planCompletionContractVersion',
    'requestSemanticsContractVersion','structuredOutputContractVersion'])
def test_incomplete_server_profile_cannot_enable_new_interpretation(field):
    r={**record(),'initialPlanResponseContractVersion':1}
    assert enabled(r);r.pop(field);assert not enabled(r)


@pytest.mark.parametrize('value',[None,True,0,2])
def test_server_owns_immutable_response_control_and_does_not_migrate_legacy(tmp_path,value):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain','deferStart':True,
            'initialPlanResponseContractVersion':value},start_async=False)
        assert enabled(r) and type(r['initialPlanResponseContractVersion']) is int
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda r:{**r,'initialPlanResponseContractVersion':value})
        old=deepcopy(r);old.pop('initialPlanResponseContractVersion');old.update(runId='legacy',idempotencyKey='old')
        repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run('legacy',lambda r:{**r,'initialPlanResponseContractVersion':1})
        assert not enabled(repo.require_run('legacy'))
    finally:facade.shutdown()
