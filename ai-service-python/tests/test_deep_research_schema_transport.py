import json
from unittest.mock import Mock

import pytest
import requests

from llm.client import DeepSeekLLM
from llm.provider import LLMRequest, LLMResult, LLMUsage, LLMProviderError
from llm.responses_transport import API_KEY
from services.deep_research.contracts import UnknownCallError, UnresolvedUnknownError, DeepResearchError, digest
from services.deep_research.planning_transport import descriptor, overhead_bytes, options_for_record
from services.deep_research.structured_output import messages
from services.deep_research.runtime import ScopedModelClient
from test_deep_research_structured_output import repository, tracked


def response(content='{"sourceRefs":[],"protocol":{},"unresolved":[]}',status='completed'):
    http=Mock(status_code=200)
    http.json.return_value={'status':status,'model':'reported-model',
        'output':[{'type':'reasoning','content':[{'type':'reasoning_text','text':'not answer'}]},
            {'type':'message','role':'assistant','content':[{'type':'output_text','text':content}]}],
        'usage':{'input_tokens':11,'output_tokens':5,'total_tokens':16}}
    return http


def test_private_physical_schema_request_and_usage_are_exact_and_cached(tmp_path,monkeypatch):
    repo=repository(tmp_path,version=14);sent=[];raw='{"sourceRefs":[],"protocol":{},"unresolved":[]}'
    def post(url,**kw):sent.append((url,kw['json']));return response(raw)
    monkeypatch.setattr('llm.client.requests.post',post)
    invoke=tracked(repo,DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid'))
    first=invoke('r','plan_experiment','Exact original source',{'max_tokens':100})
    assert sent[0][0]=='https://fixture.invalid/responses'
    wire=sent[0][1]
    assert wire['input']==messages('plan_experiment','Exact original source',14)
    assert wire['text']['format']==descriptor() and wire['max_output_tokens']==100
    assert not {API_KEY,'response_format','max_tokens','messages','tools'} & wire.keys()
    assert first['rawContent']==raw and first['reportedModel']=='reported-model'
    assert first['usage']['total_tokens']==16 and not first['usage'].get('estimated',False)
    assert invoke('r','plan_experiment','Exact original source',{'max_tokens':100})==first
    assert len(sent)==len(repo.list_calls('r'))==1
    assert repo.require_run('r')['budget']['tokens']==16


@pytest.mark.parametrize('version,node',[(13,'plan_experiment'),(14,'synthesize'),(14,'verify')])
def test_legacy_and_public_nodes_keep_chat_transport(tmp_path,monkeypatch,version,node):
    repo=repository(tmp_path,version=version);sent=[]
    http=Mock(status_code=200);http.json.return_value={'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}],
        'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
    def post(url,**kw):sent.append((url,kw['json']));return http
    monkeypatch.setattr('llm.client.requests.post',post)
    tracked(repo,DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid'))('r',node,'Evidence',{'max_tokens':100})
    assert sent[0][0].endswith('/chat/completions')
    assert sent[0][1]['response_format']=={'type':'json_object'} and API_KEY not in sent[0][1]


def test_schema_bytes_reduce_input_limit_and_are_reserved_before_dispatch(tmp_path):
    repo=repository(tmp_path,version=14);client=Mock()
    client.invoke.return_value=LLMResult('fixture','m','{}',LLMUsage(1,1,2))
    invoke=tracked(repo,client);extra=overhead_bytes(repo.require_run('r'),'plan_experiment')
    assert extra>0 and invoke.prompt_byte_limit('r','plan_experiment')==24000-extra
    with pytest.raises(ValueError,match='Prompt too large'):
        invoke('r','plan_experiment','x'*(24001-extra),{'max_tokens':100})
    client.invoke.assert_not_called();assert not repo.list_calls('r')
    reserve=Mock(wraps=repo.reserve_call)
    from services.deep_research.tools import TrackedLLMInvoker
    invoke=TrackedLLMInvoker(client,reserve,repo.complete_call,run_record_fn=repo.require_run)
    invoke('r','plan_experiment','abc',{'max_tokens':100})
    assert reserve.call_args.kwargs['budget_delta']['tokens']==3+1024+extra+100


@pytest.mark.parametrize('bad',[{API_KEY:'responses'},{'input':'replacement'},{'tools':[{}]}])
def test_caller_cannot_inject_transport_or_source_overrides(tmp_path,bad):
    repo=repository(tmp_path,version=14);client=Mock()
    with pytest.raises(ValueError):tracked(repo,client)('r','plan_experiment','Original',{'max_tokens':100,**bad})
    client.invoke.assert_not_called();assert not repo.list_calls('r')


def test_scoped_client_rejects_modified_schema_before_provider_send(tmp_path):
    repo=repository(tmp_path,version=14);provider=Mock()
    options=options_for_record(repo.require_run('r'),'plan_experiment',{'max_tokens':100})
    options['response_format']['schema']['additionalProperties']=True
    request=LLMRequest(prompt='Original',messages=messages('plan_experiment','Original',14),extra_body=options)
    client=ScopedModelClient(repo,lambda *a:True,lambda:provider).for_run('r').for_node('plan_experiment')
    with pytest.raises(DeepResearchError):client.invoke(request)
    provider.invoke.assert_not_called()


def test_received_truncation_is_settled_and_never_falls_back(tmp_path,monkeypatch):
    repo=repository(tmp_path,version=14);post=Mock(return_value=response('{"sourceRefs":[','incomplete'))
    monkeypatch.setattr('llm.client.requests.post',post)
    invoke=tracked(repo,DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid'))
    result=invoke('r','plan_experiment','Original',{'max_tokens':100})
    assert result['content']=='null' and result['rawContent']=='{"sourceRefs":['
    assert result['structuredOutput']['receivedShape']=='truncated'
    assert invoke('r','plan_experiment','Original',{'max_tokens':100})==result
    assert post.call_count==1 and repo.require_run('r')['budget']['tokens']==16


def test_unknown_schema_send_cannot_repeat_or_switch_prompt(tmp_path,monkeypatch):
    repo=repository(tmp_path,version=14);post=Mock(side_effect=requests.ReadTimeout('fixture'))
    monkeypatch.setattr('llm.client.requests.post',post)
    invoke=tracked(repo,DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid',timeout_seconds=1))
    with pytest.raises(LLMProviderError):invoke('r','plan_experiment','Original',{'max_tokens':100})
    with pytest.raises(UnknownCallError):invoke('r','plan_experiment','Original',{'max_tokens':100})
    with pytest.raises(UnresolvedUnknownError):invoke('r','plan_experiment','Changed',{'max_tokens':100})
    assert post.call_count==1 and repo.list_calls('r')[0]['status']=='unknown'


def test_complete_prepare_scope_ledger_and_physical_transport_have_same_identity(tmp_path,monkeypatch):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.experiment_planning import prepare_plan
    from services.deep_research.experiment_blueprint import columns
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.runtime import research_model_options
    from test_deep_research_compact_generation_rules import current
    from test_deep_research_request_sized_blueprint import larger
    record=current();record.update(structuredOutputContractVersion=14,experimentGenerationEnvelopeContractVersion=3)
    repo=DeepResearchRepository(tmp_path/'full.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t',**record});repo.begin_execution('r')
    raw=json.dumps(columns(larger()),ensure_ascii=False)
    post=Mock(return_value=response(raw));monkeypatch.setattr('llm.client.requests.post',post)
    provider=DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid')
    scoped=ScopedModelClient(repo,lambda *a:True,lambda:provider).for_run('r')
    invoke=TrackedLLMInvoker(scoped,repo.reserve_call,repo.complete_call,
        request_options=research_model_options,run_record_fn=repo.require_run)
    def checkpoint(value):
        return repo.update_run('r',lambda r:{**r,'state':{**r['state'],'experimentPlanning':value}})
    plan=prepare_plan(repo.require_run('r'),prompt='Exact source evidence',aliases={'E1':'original'},
        invoke=lambda node,prompt,options:invoke('r',node,prompt,options),parse=json.loads,checkpoint=checkpoint)
    assert plan['status']=='ready' and plan['basis']==larger()
    call=repo.list_calls('r')[0]
    assert call['argsDigest']==digest(plan['request'])
    assert post.call_count==1 and post.call_args.args[0].endswith('/responses')
    assert post.call_args.kwargs['json']['text']['format']==descriptor()


def test_known_http_failure_has_no_fallback(tmp_path,monkeypatch):
    repo=repository(tmp_path,version=14);http=Mock(status_code=400)
    post=Mock(return_value=http);monkeypatch.setattr('llm.client.requests.post',post)
    with pytest.raises(LLMProviderError):
        tracked(repo,DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid'))(
            'r','plan_experiment','Original',{'max_tokens':100})
    assert post.call_count==1 and repo.list_calls('r')[0]['status']=='failed'


def test_failed_response_status_cannot_be_used_even_if_text_is_valid_json(tmp_path,monkeypatch):
    repo=repository(tmp_path,version=14);post=Mock(return_value=response('{}','failed'))
    monkeypatch.setattr('llm.client.requests.post',post)
    result=tracked(repo,DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid'))(
        'r','plan_experiment','Original',{'max_tokens':100})
    assert result['rawContent']=='{}' and result['content']=='null'
    assert result['structuredOutput']['receivedShape']=='provider_failed' and post.call_count==1
