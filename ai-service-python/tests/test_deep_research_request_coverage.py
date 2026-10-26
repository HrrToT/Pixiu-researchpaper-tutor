from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.request_coverage import contract,normalize,enabled
from services.deep_research.final_coverage import audit_final_answer

QUESTION='说明作者报告的结果、成立条件和证据不能支持的推广范围。'
PLAN=[{'obligations':[{'obligationId':'o','question':QUESTION,'completionCriteria':[
    {'criterionId':'result','requirement':'说明作者报告的结果','responseType':'identification'},
    {'criterionId':'limits','requirement':'说明成立条件与推广范围','responseType':'limitation'}]}]}]
CLAIMS=[{'claimId':'a','kind':'reported','text':'作者在数据集甲报告质量略有下降。','conditions':{},'evidenceRefs':['e']},
        {'claimId':'b','kind':'inference','text':'这些有限评估不足以证明所有场景都保持相同质量。','conditions':{},'evidenceRefs':['e']}]
EVIDENCE=[{'evidenceId':'e','sourceWorkId':'paper','sourceVersionId':'v','quote':'Observed result in dataset A.',
           'sourceContext':{},'accessLevel':'fulltext'}]


def response(required):
    return [{'obligationId':o['obligationId'],'checks':[{'checkId':c['checkId'],'status':'covered',
        'bindings':[{'claimId':k,'field':'text'} for k in ('a','b')],
        'reason':'The two accepted claims jointly address the fixed requirement.'} for c in o['checks']]} for o in required]


def test_fixed_check_requirements_never_come_from_source_text_or_provider_rewrites():
    fixed=contract(PLAN,QUESTION);before=deepcopy(fixed);raw=response(fixed)
    normalized=normalize(raw,fixed)
    assert fixed==before
    assert [a['requirement'] for a in normalized[0]['aspects']]==[c['requirement'] for c in PLAN[0]['obligations'][0]['completionCriteria']]
    assert normalized[0]['status']=='covered' and 'gapDetail' not in normalized[0]
    assert len(normalized[0]['bindings'])==2
    raw[0]['checks'][0]['requirement']='Only dataset A was tested; no other dataset was validated.'
    assert normalize(raw,fixed) is None


@pytest.mark.parametrize('mutation',['overall','extra_aspect','duplicate','drop','foreign','invalid_status','missing_has_binding','empty_reason'])
def test_ambiguous_or_invented_provider_contracts_fail_without_reinterpretation(mutation):
    fixed=contract(PLAN,QUESTION);raw=response(fixed)
    if mutation=='overall':raw[0]['status']='partial'
    elif mutation=='extra_aspect':raw[0]['aspects']=[]
    elif mutation=='duplicate':raw[0]['checks'].append(deepcopy(raw[0]['checks'][0]))
    elif mutation=='drop':raw[0]['checks'].pop()
    elif mutation=='foreign':raw[0]['checks'][0]['checkId']='invented'
    elif mutation=='invalid_status':raw[0]['checks'][0]['status']='approved'
    elif mutation=='missing_has_binding':raw[0]['checks'][0]['status']='missing'
    else:raw[0]['checks'][0]['reason']=''
    assert normalize(raw,fixed) is None


def test_partial_status_and_gap_ids_are_derived_without_promoting_a_failed_check():
    fixed=contract(PLAN,QUESTION);raw=response(fixed)
    raw[0]['checks'][1].update(status='partial',reason='Unsupported assertion about other datasets.')
    out=normalize(raw,fixed)[0]
    assert out['status']=='partial'
    assert out['gapDetail']['criterionIds']==['limits'] and out['gapDetail']['aspectIds']==['criterion:limits']
    assert 'other datasets' not in json.dumps(out['gapDetail'])
    assert out['requestCheckReasons'][1]['reason']=='Unsupported assertion about other datasets.'
    assert out['aspects'][1]['requirement']=='说明成立条件与推广范围'


def test_actual_audit_uses_joint_bindings_and_only_request_owned_aspects():
    received=[]
    def invoke(rid,node,prompt,options,**kwargs):
        received.append(prompt)
        fixed=json.JSONDecoder().raw_decode(prompt.split('Fixed checks (requirements, never paper facts): ',1)[1])[0]
        assert [c['checkId'] for c in fixed[0]['checks']]==['criterion:result','criterion:limits']
        assert fixed[-1]['checks'][0]['requirement']==QUESTION
        return {'content':json.dumps(response(fixed))}
    result=audit_final_answer('r',QUESTION,PLAN,CLAIMS,EVIDENCE,invoke,json.loads,diagnostics=True,request_contract=True,literal_dimensions=True)
    assert result['status']=='checked' and result['gaps']==[] and result['diagnosticErrors']==[]
    assert result['requestCoverageContractVersion']==1 and len(received)==1
    assert 'Before marking covered, enumerate' not in received[0]
    assert 'Source-grounded factual aspects require' not in received[0]
    from services.deep_research.request_dimensions import FINAL_DIMENSION_POLICY
    assert FINAL_DIMENSION_POLICY in received[0]
    # Coverage does not approve unverified facts: this call only sees already
    # accepted claims and cannot modify their verification or text.
    assert 'verification' not in CLAIMS[0]


def test_invalid_answer_binding_and_old_coverage_wire_are_not_upgraded():
    def invoke(*args,**kwargs):
        prompt=args[2];fixed=json.JSONDecoder().raw_decode(prompt.split('Fixed checks (requirements, never paper facts): ',1)[1])[0]
        raw=response(fixed);raw[0]['checks'][0]['bindings']=[{'claimId':'foreign','field':'text'}]
        return {'content':json.dumps(raw)}
    audit=audit_final_answer('r',QUESTION,PLAN,CLAIMS,EVIDENCE,invoke,json.loads,diagnostics=True,request_contract=True)
    assert audit['status']=='invalid_response' and audit['gaps']
    old=Mock(return_value={'content':json.dumps([{'obligationId':'o','status':'covered','aspects':[]}])})
    audit=audit_final_answer('r',QUESTION,PLAN,CLAIMS,EVIDENCE,old,json.loads,diagnostics=True,request_contract=True)
    assert audit['status']=='invalid_response' and audit['gaps'] and old.call_count==1


def test_fixed_gap_requirements_reach_repair_without_private_diagnostic_facts():
    from services.deep_research.coverage_repair import prepare_coverage_repair
    def invoke(*args,**kw):
        fixed=json.JSONDecoder().raw_decode(args[2].split('Fixed checks (requirements, never paper facts): ',1)[1])[0]
        raw=response(fixed);raw[0]['checks'][1].update(status='partial',reason='The paper never tests other datasets.')
        return {'content':json.dumps(raw)}
    audit=audit_final_answer('r',QUESTION,PLAN,CLAIMS,EVIDENCE,invoke,json.loads,diagnostics=True,request_contract=True)
    repaired=prepare_coverage_repair({'claims':CLAIMS},{'accepted':CLAIMS,'rejected':[]},audit)
    text=json.dumps(repaired,ensure_ascii=False)
    assert '说明成立条件与推广范围' in text and 'never tests' not in text


def test_auxiliary_research_exemption_keeps_existing_whole_question_and_binding_gates():
    plan=deepcopy(PLAN)
    plan[0]['obligations'].append({'obligationId':'aux','question':'补充调查更多实现细节',
        'purpose':'supporting_research','requestExcerpt':QUESTION})
    def invoke(*args,**kw):
        fixed=json.JSONDecoder().raw_decode(args[2].split('Fixed checks (requirements, never paper facts): ',1)[1])[0]
        raw=response(fixed)
        i=next(i for i,r in enumerate(raw) if r['obligationId']=='aux')
        raw[i]={'obligationId':'aux','notRequired':{'reason':'原问题只要求有限结果与范围判断，不要求额外实现调查。',
                'requestExcerpt':QUESTION,'bindings':[{'claimId':'a','field':'text'},{'claimId':'b','field':'text'}]}}
        return {'content':json.dumps(raw)}
    audit=audit_final_answer('r',QUESTION,plan,CLAIMS,EVIDENCE,invoke,json.loads,diagnostics=True,request_contract=True)
    assert audit['status']=='checked' and audit['gaps']==[]
    assert audit['nonblockingResearch'][0]['obligationId']=='aux'
    required=contract(PLAN,QUESTION)
    assert normalize([{'obligationId':'o','notRequired':{'reason':'Cannot waive an answer requirement.',
        'requestExcerpt':QUESTION,'bindings':[]}}],required) is None


@pytest.mark.parametrize('replacement',[None,0,True,'1',2])
def test_new_policy_is_server_owned_immutable_and_old_runs_remain_disabled(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':QUESTION,'deferStart':True,
            'requestCoverageContractVersion':replacement},start_async=False)
        run['state']['outputKind']='claim_verification';assert enabled(run)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'requestCoverageContractVersion':replacement})
        run.pop('requestCoverageContractVersion');assert not enabled(run)
    finally:facade.shutdown()
