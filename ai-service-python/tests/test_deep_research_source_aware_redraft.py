from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.factual_source_context import factual_source_context
from services.deep_research.repair import _prepare_repair,repair_rejected
from services.deep_research.graph import make_verify_node
from services.deep_research.contracts import DeepResearchError,UnknownCallError
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.tools import TrackedLLMInvoker
from services.deep_research.verification import make_evidence,verify_claims


def inputs():
    evidence=[]
    for work,title in [('a','First paper'),('b','Second paper')]:
        quote='We evaluate speed on our own controlled platform.'
        e=make_evidence({'workId':work,'versionId':work+'-v1','contentHash':work+'-hash','accessLevel':'fulltext'},
            quote,quote,location={'page':3},obligation_ids=['o']);e['sourceTitle']=title;evidence.append(e)
    claim={'claimId':'c','text':'The platforms are identical.','kind':'inference','conditions':{},
        'evidenceRefs':[e['evidenceId'] for e in evidence],'obligationIds':['o']}
    check={'accepted':[],'rejected':[{'claimId':'c','reason':'semantic_unresolved'}]}
    requirements=[{'obligationId':'o','question':'Explain why a speed ratio is not controlled.',
        'requiredSources':['a','b'],'completionCriteria':[{'criterionId':'why','responseType':'explanation',
        'requirement':'Explain why a speed ratio is not controlled.'}]}]
    return claim,evidence,check,requirements


def context(prompt):
    return json.JSONDecoder().raw_decode(prompt.split('Frozen factual source requirements and identities (metadata, NOT paper evidence):\n',1)[1])[0]


def test_source_aware_redraft_factors_two_owners_and_their_requirements_without_changing_quotes_or_audit():
    c,e,check,requirements=inputs();before=deepcopy([c,e,check,requirements]);saved=[]
    def invoke(prompt):
        identities=context(prompt)
        assert identities['requirements']==[{'obligationId':'o','requiredSources':{'a':['P1'],'b':['P2']}}]
        assert identities['sources']['P1']['title']=='First paper'
        assert identities['sources']['P2']['sourceVersionId']=='b-v1'
        rows=json.JSONDecoder().raw_decode(prompt.split('Exact available evidence:\n',1)[1])[0]
        assert [r['sourceRef'] for r in rows]==['P1','P2']
        assert all(r['quote']==e[i]['quote'] for i,r in enumerate(rows))
        assert all(r['contentHash']==e[i]['contentHash'] for i,r in enumerate(rows))
        return {'content':'[]'}
    assert repair_rejected({'claims':[c]},check,e,'Explain',invoke,json.loads,fact_redraft=True,
        source_aware_redraft=True,requirement_context=requirements,checkpoint=lambda v:saved.append(deepcopy(v)))==[]
    pending=next(v['pending']['request']['prepared'] for v in saved if v.get('pending'))
    assert pending['originals']['c']==c and [c,e,check,requirements]==before


def test_versions_and_access_are_distinct_while_passage_hashes_do_not_relabel_the_paper():
    _,e,_,requirements=inputs()
    versions=[e[0],{**e[0],'evidenceId':'other-version','sourceVersionId':'a-v2'},
        {**e[0],'evidenceId':'abstract','accessLevel':'abstract'},
        {**e[0],'evidenceId':'other-passage','contentHash':'different-passage-hash'}]
    value,mapping=factual_source_context(versions,requirements,{'o'})
    assert len(value['sources'])==3 and len(set(mapping.values()))==3
    assert mapping['other-passage']==mapping[e[0]['evidenceId']]
    assert value['requirements'][0]['requiredSources']=={'a':['P1','P2','P3'],'b':[]}
    assert value['sources']['P3']['accessLevel']=='abstract'


def test_missing_required_work_is_visible_but_gets_no_manufactured_source_or_citation():
    c,e,check,requirements=inputs();c['evidenceRefs']=[e[0]['evidenceId']]
    prepared=_prepare_repair({'claims':[c]},check,[e[0]],'Explain',fact_redraft=True,
        source_aware_redraft=True,requirement_context=requirements)
    identities=context(prepared['prompt'])
    assert identities['requirements'][0]['requiredSources']['b']==[]
    assert list(identities['sources'])==['P1']
    assert prepared['allowed']=={'c':[e[0]['evidenceId']]}


def test_old_mode_keeps_its_existing_prompt_and_designs_keep_configuration_view():
    c,e,check,requirements=inputs()
    old=_prepare_repair({'claims':[c]},check,e,'Explain',fact_redraft=True,requirement_context=requirements)
    default=_prepare_repair({'claims':[c]},check,e,'Explain',fact_redraft=True,
        requirement_context=requirements,source_aware_redraft=False)
    assert old==default and 'Frozen factual source requirements' not in old['prompt']
    proposal={**c,'kind':'proposal'}
    prepared=_prepare_repair({'claims':[proposal]},check,e,'Design',fact_redraft=True,
        source_aware_redraft=True,requirement_context=requirements)
    assert proposal['text'] in prepared['prompt'] and 'Frozen factual source requirements' not in prepared['prompt']


@pytest.mark.parametrize('marker',[None,True,1,2])
def test_actual_graph_passes_source_requirements_only_for_new_marked_runs(marker,monkeypatch):
    c,e,check,requirements=inputs()
    record={'factRedraftContractVersion':marker,'state':{'reportBody':{'claims':[c]},'evidence':e,
        'plan':[{'itemId':'i','obligations':requirements}]}}
    def update(rid,mutate,**kwargs):
        nonlocal record
        record=mutate(deepcopy(record));return deepcopy(record)
    monkeypatch.setattr('services.deep_research.final_coverage.audit_final_answer',lambda *a,**kw:{'status':'not_requested','gaps':[]})
    captured=[]
    def invoke(rid,node,prompt,options):
        captured.append(prompt)
        assert ('Frozen factual source requirements' in prompt) is (type(marker) is int and marker==2)
        if type(marker) is int and marker==2:
            assert context(prompt)['requirements'][0]['requiredSources']=={'a':['P1'],'b':['P2']}
        return {'content':'[]'}
    make_verify_node(Mock(return_value=check),None,update,llm_invoke=invoke)({'run_id':'r'})
    assert len(captured)==1 and not record['state']['verifiedReport']['verifiedClaims']


def test_unknown_source_aware_repair_keeps_exact_request_and_rejects_changed_source_requirements(tmp_path):
    from llm.provider import LLMProviderError
    c,e,check,requirements=inputs();saved=[]
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();repo.create_run({'runId':'r','taskId':'t'});repo.begin_execution('r')
    provider=Mock();provider.invoke.side_effect=LLMProviderError('unknown',provider='fixture',model='fixture')
    invoker=TrackedLLMInvoker(provider,repo.reserve_call,repo.complete_call)
    def invoke(prompt):return invoker('r','repair_claims',prompt,{'max_tokens':1000})
    kwargs={'fact_redraft':True,'source_aware_redraft':True,'requirement_context':requirements,
        'checkpoint':lambda v:saved.append(deepcopy(v))}
    with pytest.raises(LLMProviderError):repair_rejected({'claims':[c]},check,e,'Explain',invoke,json.loads,**kwargs)
    pending=deepcopy(saved[-1])
    with pytest.raises(UnknownCallError):repair_rejected({'claims':[c]},check,e,'Explain',invoke,json.loads,batch_state=pending,**kwargs)
    changed=deepcopy(requirements);changed[0]['requiredSources']=['a']
    with pytest.raises(DeepResearchError):repair_rejected({'claims':[c]},check,e,'Explain',invoke,json.loads,
        batch_state=pending,**{**kwargs,'requirement_context':changed})
    assert provider.invoke.call_count==1


def test_source_metadata_is_not_semantic_approval_and_aliases_stay_out_of_the_published_body():
    c,e,_,_=inputs();c['text']='Both platforms are identical.'
    negative=Mock(return_value=[{'claimId':'c','status':'failed','reason':'Not established by the actual quotations'}])
    assert verify_claims([c],e,negative)['rejected'][0]['reason']=='semantic_unresolved'
    negative.assert_called_once();negative.reset_mock()
    c['text']='P1 confirms both platforms are identical.'
    assert verify_claims([c],e,negative)['rejected'][0]['reason']=='internal_reference_in_prose'
    negative.assert_not_called()


def test_existing_version_one_run_cannot_be_upgraded_to_change_a_saved_request(tmp_path):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    repo.create_run({'runId':'old','taskId':'t','factRedraftContractVersion':1})
    with pytest.raises(ValueError,match='Immutable'):
        repo.update_run('old',lambda r:{**r,'factRedraftContractVersion':2})
    assert repo.require_run('old')['factRedraftContractVersion']==1


def test_fixed_source_metadata_overflow_stops_before_any_provider_request():
    from services.deep_research.contracts import BudgetExhaustedError
    c,e,check,requirements=inputs()
    for row in e:row['sourceTitle']='Long untrusted title '*2000
    invoke=Mock()
    with pytest.raises(BudgetExhaustedError):
        repair_rejected({'claims':[c]},check,e,'Explain',invoke,json.loads,fact_redraft=True,
            source_aware_redraft=True,requirement_context=requirements)
    invoke.assert_not_called()
