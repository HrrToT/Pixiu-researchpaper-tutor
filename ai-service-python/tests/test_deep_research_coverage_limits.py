from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.coverage_limits import validate,enabled
from services.deep_research.request_coverage import normalize
from services.deep_research.final_coverage import audit_final_answer

QUESTION='说明方法适用条件及不能据此推出的结论。'
TEXT='该推导只校正初始化项，不能据此保证所有训练都更快。'
CLAIMS=[{'claimId':'c','text':TEXT,'conditions':{},'kind':'inference','evidenceRefs':[]}]
PLAN=[{'obligations':[{'obligationId':'o','question':QUESTION,'purpose':'answer_requirement',
    'completionCriteria':[{'criterionId':'limit','requirement':QUESTION,'responseType':'limitation'}]}]}]
REQUIREMENTS=[{'obligationId':'o','question':QUESTION,'purpose':'answer_requirement',
    'checks':[{'checkId':'criterion:limit','criterionId':'limit','requirement':QUESTION,'responseType':'limitation'}]}]
SPAN={'claimId':'c','field':'text','excerpt':TEXT}
def row(spans):return [{'obligationId':'o','checks':[{'checkId':'criterion:limit','status':'covered',
    'bindings':[{'claimId':'c','field':'text'}],'reason':'Fixture actual boundary explained.','limitSpans':spans}]}]


def test_empty_implicit_boundary_cannot_close_check_but_explicit_literal_can():
    data=row([]);data[0]['checks'][0]['reason']='The answer implicitly limits the claim by not making a guarantee.'
    result=normalize(data,REQUIREMENTS,claims=CLAIMS,literal_limits=True)
    assert result[0]['status']=='partial' and result[0]['limitAudits'][0]['errors']==['missing_explicit_limit_span']
    assert '正文' in result[0]['gapDetail']['missingContent']
    # Literal existence is a prerequisite, never an independent semantic verdict.
    assert normalize(row([SPAN]),REQUIREMENTS,claims=CLAIMS,literal_limits=True)[0]['status']=='covered'
    old=deepcopy(data);old[0]['checks'][0].pop('limitSpans')
    assert normalize(old,REQUIREMENTS,claims=CLAIMS)[0]['status']=='covered'
    assert normalize(old,REQUIREMENTS,claims=CLAIMS,literal_limits=True) is None


@pytest.mark.parametrize('mutation',['foreign','source_field','missing_text','empty','extra_key','duplicate','ambiguous_id','unbound_field','empty_conditions'])
def test_invalid_or_unaccepted_span_cannot_close_limit(mutation):
    spans=[deepcopy(SPAN)];claims=deepcopy(CLAIMS)
    if mutation=='foreign':spans[0]['claimId']='rejected'
    elif mutation=='source_field':spans[0]['field']='quote'
    elif mutation=='missing_text':spans[0]['excerpt']='Source-only statement not in accepted answer.'
    elif mutation=='empty':spans[0]['excerpt']=' '
    elif mutation=='extra_key':spans[0]['sourceId']='source'
    elif mutation=='duplicate':spans.append(deepcopy(spans[0]))
    elif mutation=='ambiguous_id':claims.append(deepcopy(claims[0]))
    elif mutation=='unbound_field':claims[0]['conditions']={'限制':'仅适用于凸问题'};spans[0].update(field='conditions',excerpt='仅适用于凸问题')
    elif mutation=='empty_conditions':spans[0].update(field='conditions',excerpt='{}')
    result=normalize(row(spans),REQUIREMENTS,claims=claims,literal_limits=True)
    assert result[0]['status']=='partial' and result[0]['limitAudits'][0]['errors']


@pytest.mark.parametrize('request_contract',[3,4,5])
@pytest.mark.parametrize('spans',[[],[SPAN]])
def test_actual_audit_keeps_literal_anchor_and_all_existing_coverage_checks(request_contract,spans):
    def invoke(rid,node,prompt,options,**kwargs):
        assert 'An unstated guarantee is NOT an explicit boundary' in prompt
        assert 'Factual support was checked separately' in prompt
        raw=prompt.rsplit('Fixed checks (requirements, never paper facts): ',1)[1]
        requirements=json.JSONDecoder().raw_decode(raw)[0]
        output=[]
        for o in requirements:
            checks=[]
            for c in o['checks']:
                checks.append({'checkId':c['checkId'],'status':'covered','bindings':[{'claimId':'c','field':'text'}],
                    'reason':'Fixture accepted prose contains the bounded conclusion.',
                    **({'limitSpans':spans} if c.get('responseType')=='limitation' else {})})
            output.append({'obligationId':o['obligationId'],'checks':checks})
        return {'content':json.dumps(output)}
    original=deepcopy((PLAN,CLAIMS))
    result=audit_final_answer('r',QUESTION,PLAN,CLAIMS,[],invoke,json.loads,
        request_contract=request_contract,diagnostics=True,consolidated_instructions=True,literal_limits=True)
    assert result['status']=='checked' and bool(result['gaps']) is (not bool(spans))
    assert result['coverageLimitContractVersion']==1 and original==(PLAN,CLAIMS)


def test_partial_missing_and_multiclaim_conditions_stay_scoped_to_bound_accepted_fields():
    claims=deepcopy(CLAIMS)+[{'claimId':'d','text':'其他说明。','conditions':{'范围':'仅适用于凸问题'}}]
    bindings=[{'claimId':'c','field':'text'},{'claimId':'d','field':'conditions'}]
    assert validate([SPAN,{'claimId':'d','field':'conditions','excerpt':'仅适用于凸问题'}],claims,bindings,covered=True)==[]
    data=row([]);data[0]['checks'][0]['status']='missing';data[0]['checks'][0]['bindings']=[]
    result=normalize(data,REQUIREMENTS,claims=claims,literal_limits=True)
    assert result[0]['status']=='missing' and result[0]['limitAudits'][0]['errors']==[]


@pytest.mark.parametrize('value',[None,True,False,0,2,1.0,'1'])
def test_exact_frozen_policy_only(value):
    r={'coverageLimitContractVersion':value,'coverageInstructionsContractVersion':1,'requestCoverageContractVersion':5}
    assert not enabled(r)
    r['coverageLimitContractVersion']=1;assert enabled(r)
    r['coverageInstructionsContractVersion']=True;assert not enabled(r)


@pytest.mark.parametrize('value',[1,None,'true'])
def test_invalid_direct_flag_rejected_without_call(value):
    invoke=Mock()
    with pytest.raises(ValueError):audit_final_answer('r',QUESTION,PLAN,CLAIMS,[],invoke,json.loads,literal_limits=value)
    invoke.assert_not_called()


def test_server_owns_immutable_policy_and_cannot_add_it_to_legacy_run(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':QUESTION,'deferStart':True,
            'coverageLimitContractVersion':False},start_async=False)
        assert enabled(r)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(r['runId'],lambda r:{**r,'coverageLimitContractVersion':False})
        old=deepcopy(r);old.pop('coverageLimitContractVersion');old.update(runId='legacy',idempotencyKey='old');repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('legacy',lambda r:{**r,'coverageLimitContractVersion':1})
        assert not enabled(repo.require_run('legacy'))
    finally:facade.shutdown()
