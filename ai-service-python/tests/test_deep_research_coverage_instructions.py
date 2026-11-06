from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.final_coverage import audit_final_answer
from services.deep_research.shared_strings import unpack
from services.deep_research.nested_tables import unpack as untables
from test_deep_research_request_coverage import QUESTION,PLAN,CLAIMS,EVIDENCE,response


def inputs(prompt):
    raw=prompt.rsplit('Exact decision input fields (question, fixed checks, complete accepted claims and server metadata):\n',1)[1]
    value=json.JSONDecoder().raw_decode(raw)[0]
    return untables(unpack(value)) if set(value)=={'strings','value'} else value


def run(mutation=None):
    sent=[]
    def invoke(rid,node,prompt,options,**kwargs):
        sent.append(prompt);payload=inputs(prompt);rows=response(payload['requirements'])
        if mutation=='foreign':rows[0]['checks'][0]['bindings']=[{'claimId':'foreign','field':'text'}]
        elif mutation=='conditions':rows[0]['checks'][0]['bindings']=[{'claimId':'a','field':'conditions'}]
        elif mutation=='metadata':rows[0]['checks'][0]['bindings']=[{'claimId':'a','field':'sourceAccessSummary'}]
        elif mutation=='missing_check':rows[0]['checks'].pop()
        elif mutation=='extra_check':rows[0]['checks'].append({**deepcopy(rows[0]['checks'][0]),'checkId':'invented'})
        elif mutation=='waive_answer':rows[0]={'obligationId':rows[0]['obligationId'],'notRequired':{'reason':'This answer request is allegedly unnecessary.','requestExcerpt':QUESTION,'bindings':[{'claimId':'a','field':'text'}]}}
        elif mutation=='partial':rows[0]['checks'][0].update(status='partial',reason='The fixed result still lacks its requested conditions.')
        rows.append({'auditType':'answer_coherence','coherent':mutation!='incoherent','issues':[] if mutation!='incoherent' else [{'kind':'scope_ambiguity','bindings':[{'claimId':'a','field':'text'}],'reason':'Fixture actual joint scope conflict.'}]})
        return {'content':json.dumps(rows)}
    before=deepcopy((PLAN,CLAIMS,EVIDENCE))
    result=audit_final_answer('r',QUESTION,PLAN,CLAIMS,EVIDENCE,invoke,json.loads,
        request_contract=5,diagnostics=True,literal_dimensions=True,coherence=True,
        task_sources=True,request_semantics=2,binding_catalog=True,scoped_catalog=True,
        shared_decision_inputs=True,shared_evidence_context=True,consolidated_instructions=True)
    assert (PLAN,CLAIMS,EVIDENCE)==before and len(sent)==1
    return result,sent[0]


def test_consolidated_request_keeps_full_inputs_and_unchanged_binding_and_coherence_checks():
    result,prompt=run();payload=inputs(prompt)
    assert result['status']=='checked' and not result['gaps']
    assert result['coverageInstructionsContractVersion']==1
    assert payload['question']==QUESTION and len(payload['claims'])==len(CLAIMS)
    for actual,old in zip(payload['claims'],CLAIMS):
        assert actual['text']==old['text'] and actual['conditions']==old['conditions']
    assert payload['requirements'][0]['checks'][0]['requirement']==PLAN[0]['obligations'][0]['completionCriteria'][0]['requirement']
    assert 'Factual support was checked separately' in prompt


@pytest.mark.parametrize('mutation',['foreign','conditions','metadata','missing_check','extra_check','waive_answer'])
def test_existing_validation_still_rejects_invalid_or_invented_coverage(mutation):
    result,_=run(mutation);assert result['status']=='invalid_response' and result['gaps']


@pytest.mark.parametrize('mutation',['partial','incoherent'])
def test_negative_decisions_remain_negative(mutation):
    result,_=run(mutation);assert result['gaps']
    if mutation=='incoherent':assert result['answerCoherence']['coherent'] is False


@pytest.mark.parametrize('bad',[1,None,'true'])
def test_consolidated_policy_is_strict_bool(bad):
    with pytest.raises(ValueError):audit_final_answer('r',QUESTION,PLAN,CLAIMS,EVIDENCE,Mock(),json.loads,request_contract=5,consolidated_instructions=bad)


def test_full_required_context_overflow_still_stops_before_provider_dispatch():
    huge=[{**EVIDENCE[0],'quote':'z'*40000,'sourceContext':{'before':'complete '*4000,'after':'unchanged '*4000}}]
    invoke=Mock()
    result=audit_final_answer('r',QUESTION,PLAN,CLAIMS,huge,invoke,json.loads,request_contract=5,
        diagnostics=True,shared_evidence_context=True,consolidated_instructions=True)
    assert result['status']=='budget_exhausted' and result['budgetLimit']['kind']=='coveragePromptBytes'
    invoke.assert_not_called()


@pytest.mark.parametrize('overlap',[False,True])
def test_process_roles_still_require_actual_operations_and_disjoint_request_spans(overlap):
    q='如何把输入视图转换为深度图？';plan=[{'obligations':[{'obligationId':'o','question':q}]}]
    claims=[{'claimId':'c','kind':'reported','text':'计算法线和距离并转换为深度图。','conditions':{}}]
    def invoke(rid,node,prompt,options,**kwargs):
        value=inputs(prompt);rows=[]
        for o in value['requirements']:
            rows.append({'obligationId':o['obligationId'],'checks':[{'checkId':c['checkId'],'status':'covered','bindings':[{'claimId':'c','field':'text'}],'reason':'Fixture operation is present in the answer.','processLinks':[{'input':{'request':q if overlap else '输入视图'},'operation':{'id':'c','field':'text','excerpt':'计算法线和距离并转换为深度图'},'output':{'request':q if overlap else '深度图'}}]} for c in o['checks']]})
        assert 'Never copy the whole question into both' in prompt
        return {'content':json.dumps(rows)}
    result=audit_final_answer('r',q,plan,claims,[],invoke,json.loads,request_contract=5,diagnostics=True,
        shared_decision_inputs=True,consolidated_instructions=True)
    assert (result['status']=='checked' and not result['gaps']) is (not overlap)


@pytest.mark.parametrize('client_value',[None,True,0,2])
def test_server_owned_instruction_policy_is_immutable_and_absent_from_old_runs(tmp_path,client_value):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        record,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':QUESTION,'deferStart':True,'coverageInstructionsContractVersion':client_value},start_async=False)
        assert record['coverageInstructionsContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(record['runId'],lambda r:{**r,'coverageInstructionsContractVersion':client_value})
        old=deepcopy(record);old.update(runId='legacy',idempotencyKey='old');old.pop('coverageInstructionsContractVersion')
        repo.create_run(old);before=repo.require_run('legacy')
        facade.create({'workspaceTaskId':'t','operationKey':'next','question':QUESTION,'deferStart':True},start_async=False)
        assert repo.require_run('legacy')==before
    finally:facade.shutdown()


@pytest.mark.parametrize('kind',['experiment_design','unsupported_kind'])
def test_non_fixed_request_modes_never_opt_into_new_instructions(kind):
    from services.deep_research.graph import make_verify_node
    record={'coverageInstructionsContractVersion':1,'coverageInputContractVersion':1,'requestCoverageContractVersion':5,'question':'研究问题','state':{'outputKind':kind,'reportBody':{'claims':[]},'evidence':[]},'budget':{}}
    def update(rid,fn,**kwargs):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    make_verify_node(lambda *a:{'accepted':[],'rejected':[]},None,update)({'run_id':'r'})
    assert 'coverageInstructionsContractVersion' not in record['state']['verifiedReport']['answerCoverage']
