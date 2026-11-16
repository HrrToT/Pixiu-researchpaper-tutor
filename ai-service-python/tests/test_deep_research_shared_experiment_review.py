from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError, UnknownCallError, digest
from services.deep_research.shared_experiment_generation import prepare as generate
from services.deep_research.shared_experiment_review import targets, prepare, assess, descriptor, NODE, _pointer
from services.deep_research.shared_experiment_result import compile_candidate, validate_candidate
from test_deep_research_shared_experiment_generation import context, response as generation_response
from test_deep_research_shared_experiment_plan import proposal


def ready(value=None):
    r, data, aliases = context()
    def checkpoint(v): r['state']['sharedExperimentGeneration'] = deepcopy(v)
    generate(r,data,aliases,invoke=Mock(return_value=generation_response(value)),checkpoint=checkpoint)
    return r,data,aliases


def verdict(r, data):
    p = r['state']['sharedExperimentGeneration']['boundProposal']['proposal']
    paths = {'attribution':'/sourceFacts/0/text', 'data':'/data/trainingSplit',
             'initialization':'/states/1/representation', 'interventions':'/factors/0/onOperation/action',
             'pairing_timeline':'/pairing/identityChecks', 'budgets':'/budgets/0/stopRule',
             'measurement':'/metrics/0/procedure', 'analysis':'/analysis/decisionRule',
             'human_requirement':'/hypothesis'}
    checks = []
    for target in targets(r):
        path = target['pathPrefixes'][0] if target['kind']=='source_fact' else paths[target['kind']]
        text = _pointer(p,path)
        checks.append({'checkId':target['checkId'],'status':'passed',
            'planBindings':[{'path':path,'text':text}],
            'evidenceBindings':[{'evidenceId':'E1','field':'quote','text':data['evidence'][0]['quote']}]
                if target['kind'] in ('source_fact','attribution') else [], 'reason':'人工接口夹具，不能计入真实科学验收。'})
    return {'checks':checks,'coherent':True,'issues':[]}


def reply(v): return {'content':json.dumps(v,ensure_ascii=False),'finishReason':'stop'}


def check(r,data,aliases,v=None):
    sent = Mock(return_value=reply(verdict(r,data) if v is None else v))
    states = []
    def checkpoint(value):
        r['state']['sharedExperimentReview'] = deepcopy(value); states.append(deepcopy(value))
    result = prepare(r,data,aliases,invoke=sent,checkpoint=checkpoint)
    return result,sent,states,checkpoint


def test_complete_review_covers_every_fact_section_and_frozen_criterion_then_reuses_receipt():
    r,data,aliases = ready(); before=deepcopy(r['state']['sharedExperimentGeneration'])
    result,sent,states,checkpoint = check(r,data,aliases)
    assert [s['status'] for s in states] == ['pending','response_received','checked']
    assert result['assessment']['valid'] and result['assessment']['complete']
    assert len(result['assessment']['verdict']['checks']) == len(targets(r))
    assert prepare(r,data,aliases,invoke=sent,checkpoint=checkpoint) == result
    assert sent.call_count == 1 and r['state']['sharedExperimentGeneration'] == before
    assert not r['state'].get('reportBody') and not r.get('publication')


@pytest.mark.parametrize('mutation', ['missing','duplicate','unknown','fake_plan','wrong_section','identifier_only',
                                    'missing_fact_evidence','foreign_evidence','nonliteral_evidence','coherence',
                                    'truncated','duplicate_json'])
def test_malformed_or_unbound_positive_verdict_never_grants_approval(mutation):
    r,data,aliases=ready(); v=verdict(r,data); response=None
    if mutation=='missing': v['checks'].pop()
    elif mutation=='duplicate': v['checks'][-1]=deepcopy(v['checks'][0])
    elif mutation=='unknown': v['checks'][0]['checkId']='unknown'
    elif mutation=='fake_plan': v['checks'][0]['planBindings'][0]['text']='invented'
    elif mutation=='wrong_section': v['checks'][2]['planBindings']=[{'path':'/hypothesis','text':_pointer(r['state']['sharedExperimentGeneration']['boundProposal']['proposal'],'/hypothesis')}]
    elif mutation=='identifier_only': v['checks'][0]['planBindings']=[{'path':'/sourceFacts/0/id','text':'F1'}]
    elif mutation=='missing_fact_evidence': v['checks'][0]['evidenceBindings']=[]
    elif mutation=='foreign_evidence': v['checks'][0]['evidenceBindings'][0]['evidenceId']='E2'
    elif mutation=='nonliteral_evidence': v['checks'][0]['evidenceBindings'][0]['text']='unsupported original quote'
    elif mutation=='coherence': v['coherent']=False
    elif mutation=='truncated': response={**reply(v),'finishReason':'length'}
    else: response={**reply(v),'content':reply(v)['content'].replace('"coherent": true','"coherent": true,"coherent":true')}
    result=assess(r,data,aliases,response or reply(v))
    assert result['valid'] is False and result['scientificApproval'] is False


def test_failed_scientific_check_remains_a_real_gap_and_cannot_compile_a_result():
    r,data,aliases=ready(); v=verdict(r,data)
    v['checks'][3].update(status='failed',reason='初始化操作与实际表示不兼容。')
    result,_,_,_=check(r,data,aliases,v)
    assert result['assessment']['valid'] and not result['assessment']['complete']
    with pytest.raises(DeepResearchError) as error: compile_candidate(r,data,aliases)
    assert error.value.code=='shared_experiment_incomplete'


def test_negative_review_may_bind_actual_availability_or_identity_without_becoming_invalid():
    r,data,aliases=ready();v=verdict(r,data)
    v['checks'][2].update(status='unresolved',reason='需要进一步确认实际准备步骤。',
        planBindings=[{'path':'/data/inputs/0/availability','text':'prepare'}])
    v.update(coherent=False,issues=[{'reason':'初始化依赖尚未解决。',
        'planBindings':[{'path':'/states/0/id','text':'raw'}]}])
    result=assess(r,data,aliases,reply(v))
    assert result['valid'] and not result['scientificApproval']


def test_unresolved_prerequisite_cannot_be_waived_by_all_passed_model_checks():
    p=proposal(); p['unresolved']=['Required initial asset has no preparation recipe.']
    r,data,aliases=ready(p); result,_,_,_=check(r,data,aliases)
    assert result['assessment']['valid'] and not result['assessment']['scientificApproval']


def test_existing_number_precheck_stops_before_independent_model_request():
    p=proposal(); p['sourceFacts'][0]['text']='The paper reports 999 MB of storage.'
    r,data,aliases=ready(p); sent=Mock(); saved=[]
    result=prepare(r,data,aliases,invoke=sent,checkpoint=saved.append)
    assert result['status']=='not_started_precheck' and result['hardIssues']
    sent.assert_not_called()
    assert assess(r,data,aliases,reply(verdict(r,data)))['scientificApproval'] is False


def test_unknown_review_is_preserved_and_not_automatically_repeated():
    r,data,aliases=ready(); sent=Mock(side_effect=UnknownCallError('original'))
    def checkpoint(v): r['state']['sharedExperimentReview']=deepcopy(v)
    with pytest.raises(UnknownCallError): prepare(r,data,aliases,invoke=sent,checkpoint=checkpoint)
    with pytest.raises(DeepResearchError): prepare(r,data,aliases,invoke=sent,checkpoint=checkpoint)
    assert sent.call_count==1


def test_candidate_is_compiled_from_same_definitions_and_still_requires_final_audit():
    r,data,aliases=ready(); check(r,data,aliases)
    result=compile_candidate(r,data,aliases)
    assert result['publishable'] is False and result['finalAnswerAuditRequired'] is True
    assert validate_candidate(result,r,data,aliases)
    assert result['citations'][0]['evidenceId']==aliases['E1']
    assert '尚未执行' in result['markdown'] and '999' not in result['markdown']
    assert 'SH coefficients' in result['markdown'] and 'scale and rotation' in result['markdown']
    assert '训练划分' in result['markdown'] and '100 优化步' in result['markdown'] and '10 优化步' in result['markdown']
    result['markdown']+='\nInvented extra result.'
    assert not validate_candidate(result,r,data,aliases)


@pytest.mark.parametrize('mutation',['proposal','review_response','review_verdict','evidence','budget_limit'])
def test_edit_after_review_cannot_reuse_result_or_approval(mutation):
    r,data,aliases=ready(); check(r,data,aliases)
    if mutation=='proposal': r['state']['sharedExperimentGeneration']['boundProposal']['proposal']['budgets'][1]['cap']=999
    elif mutation=='review_response': r['state']['sharedExperimentReview']['response']['content']='{}'
    elif mutation=='review_verdict': r['state']['sharedExperimentReview']['assessment']['verdict']['checks'][0]['reason']='rewritten'
    elif mutation=='evidence': data['evidence'][0]['quote']='changed source'
    else: r['budget']['maxTokens']+=1
    with pytest.raises((DeepResearchError,ValueError)): compile_candidate(r,data,aliases)


def test_actual_scoped_tracked_review_schema_and_reuse(tmp_path,monkeypatch):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.runtime import ScopedModelClient,research_model_options
    from llm.client import DeepSeekLLM
    from test_deep_research_schema_transport import response as http_response
    r,data,aliases=ready(); repo=DeepResearchRepository(tmp_path/'r.sqlite3'); repo.initialize()
    repo.create_run(r); repo.begin_execution('r')
    post=Mock(return_value=http_response(json.dumps(verdict(r,data))))
    monkeypatch.setattr('llm.client.requests.post',post)
    provider=DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid')
    client=ScopedModelClient(repo,lambda *args:True,lambda:provider).for_run('r')
    invoker=TrackedLLMInvoker(client,repo.reserve_call,repo.complete_call,request_options=research_model_options,
        run_record_fn=repo.require_run,experiment_max_input_bytes=32000)
    def checkpoint(v): repo.update_run('r',lambda r:{**r,'state':{**r['state'],'sharedExperimentReview':deepcopy(v)}})
    def run(): return prepare(repo.require_run('r'),data,aliases,checkpoint=checkpoint,
        invoke=lambda node,prompt,opts:invoker('r',node,prompt,opts,use_reserve=True))
    result=run()
    assert result['assessment']['complete'] and result['status']=='checked'
    assert run()==result and post.call_count==1
    assert repo.list_calls('r')[0]['argsDigest']==digest(result['request'])
    wire=post.call_args.kwargs['json']
    assert wire['text']['format']==descriptor(repo.require_run('r')) and wire['max_output_tokens']==4096
    assert invoker.prompt_byte_limit('r',NODE)==32000
