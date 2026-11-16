from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.comparison_cells import plan_cells,compile_cells,partition_source_bound_claims
from services.deep_research.comparison_presentation import metadata,audit_digest,revalidate_audit
from services.deep_research.comparison_intent import guidance,GUIDANCE
from services.deep_research.authored_body import decode
from services.deep_research.verification import make_evidence,verify_claims
from services.deep_research.reporting import render_report
from test_deep_research_comparison_intent import packets,obligation,QUESTION,record


def fixture(marked=True):
    cp,_=packets()
    question=QUESTION+'数字只选一组同口径基线对照。'
    target=obligation('example','joint','同口径数字','数字只选一组')
    target.update(requiredSourceAliases=['P1','P2'],requestExcerpt='数字只选一组同口径基线对照')
    target['completionCriteria']=[{'criterionId':'matched','requirement':'给一组同口径基线数字，保留条件。','responseType':'identification'}]
    requirements=[*cp['requirements'],target]
    quote='Table row 1: Baseline | 100 | 10MB\nTable row 2: Variant | 150 | 6MB'
    ev=make_evidence({'workId':'left','versionId':'left-v1','contentHash':'hash','accessLevel':'fulltext'},
        quote,quote,location={'table':'t1'},obligation_ids=['example'])
    ev['tableData']={'groups':[['Bench',['FPS','Size']]],'rows':[[1,'Baseline',['100','10MB']],[2,'Variant',['150','6MB']]]}
    wire={'evidenceId':'E1','source':'P1','obligations':['example'],'quote':quote,'tableData':ev['tableData']}
    cp=plan_cells(requirements,cp['sources'],[wire],shared_axes=True,typed_roles=True,question=question,joint_reports=marked)
    bindings=[{'evidenceId':'E1','rowNumber':n,'groupIndex':0,'metric':m,'value':v}
        for n,_,values in ev['tableData']['rows'] for m,v in zip(['FPS','Size'],values)]
    point={'kind':'reported','body':{'prose':{'text':'Bench 同口径结果：Baseline FPS 100、Size 10MB；Variant FPS 150、Size 6MB。','conditions':{}}},
           'evidenceRefs':['E1'],'tableBindings':bindings,'detailLevel':'concise'}
    payload={'cells':[],'conclusions':[{'obligationIds':['example'],'claim':point}]}
    return cp,payload,ev,question


def compiled():
    cp,payload,ev,question=fixture();draft=compile_cells(payload,cp,max_claims=5);draft['sources']=cp['sources']
    c=decode(draft['report']['claims'][0]);c['evidenceRefs']=[ev['evidenceId']]
    for b in c['tableBindings']:b['evidenceId']=ev['evidenceId']
    return cp,draft,c,ev,question


def test_shared_reported_example_does_not_force_a_second_source_or_waive_other_goals():
    cp,draft,claim,ev,_=compiled()
    assert draft['jointReports'] is True and claim['kind']=='reported'
    assert not any(c['obligationId']=='example' for c in cp['cells'])
    assert len(cp['cells'])==2 and {'mechanism','fairness','choice'}<=set(draft['unresolvedObligationIds'])
    retained,rejected=partition_source_bound_claims([claim],draft,[ev])
    assert retained==[claim] and not rejected
    check=Mock(return_value=[{'claimId':claim['claimId'],'status':'passed'}])
    verified=verify_claims([claim],[ev],check,table_references_version=4)
    assert len(verified['accepted'])==1
    assert verified['accepted'][0]['kind']=='reported' and verified['accepted'][0]['verification']=='semantic_passed'
    assert verified['accepted'][0]['text']==claim['text']
    text=render_report({'claims':verified['accepted'],'evidence':[ev],'comparisonCells':metadata(draft),
                        'outputKind':'paper_comparison','presentationVersion':4})
    assert claim['text'] in text and '10MB' in text and '6MB' in text


def test_historical_compiler_still_refuses_reported_joint_and_prompt_is_unchanged():
    cp,payload,_,_=fixture(False);draft=compile_cells(payload,cp,max_claims=5)
    assert not draft['report']['claims'] and draft['errors']
    assert 'jointReports' not in cp and 'jointReports' not in draft
    r=record();assert guidance(r)==GUIDANCE
    r.update(comparisonPlanningContractVersion=2,comparisonJointReportsContractVersion=1)
    assert 'SINGLE baseline example' in guidance(r) and 'not a separate numerical inventory' in guidance(r)


@pytest.mark.parametrize('mutation',['foreign','version','goal'])
def test_edited_example_keeps_exact_goal_and_source_version_scope(mutation):
    _,draft,c,ev,_=compiled()
    if mutation=='foreign':ev['sourceWorkId']='other'
    elif mutation=='version':ev['sourceVersionId']='left-v2'
    else:c['obligationIds']=['mechanism']
    accepted,rejected=partition_source_bound_claims([c],draft,[ev])
    assert not accepted and rejected[0]['reason']=='comparison_joint_scope_mismatch'


@pytest.mark.parametrize('mutation',['value','metric','row','dataset','negative_semantic'])
def test_reported_kind_preserves_numeric_and_independent_semantic_checks(mutation):
    _,_,c,ev,_=compiled()
    if mutation=='value':c['tableBindings'][0]['value']='999'
    elif mutation=='metric':c['tableBindings'][0]['metric']='PSNR'
    elif mutation=='row':c['tableBindings'][0]['rowNumber']=99
    elif mutation=='dataset':c['text']=c['text'].replace('Bench','Other')
    checker=Mock(return_value=[{'claimId':c['claimId'],'status':'failed' if mutation=='negative_semantic' else 'passed'}])
    assert not verify_claims([c],[ev],checker,table_references_version=4)['accepted']


@pytest.mark.parametrize('mutation',['policy','kind','text','binding','reference'])
def test_reported_policy_and_joint_fact_are_bound_to_final_audit_digest(mutation):
    _,draft,c,_,_=compiled();meta=metadata(draft)
    audit={'comparisonPresentationDigest':audit_digest(meta,[c]),'gaps':[]}
    assert revalidate_audit(audit,meta,[c])==audit
    if mutation=='policy':meta.pop('jointReports')
    elif mutation=='kind':c['kind']='inference'
    elif mutation=='text':c['text']+=' New unsupported scope.'
    elif mutation=='binding':c['tableBindings'][0]['value']='999'
    else:c['evidenceRefs']=['foreign']
    assert revalidate_audit(audit,meta,[c])['status']=='invalidated_comparison_presentation'


def test_server_selects_and_freezes_joint_report_policy(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.comparison_generation import planning_options
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **kwargs:None,llm_client=object(),comparison_cells_version=1)
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':QUESTION,
            'comparisonJointReportsContractVersion':0},start_async=False)
        assert r['comparisonJointReportsContractVersion']==1
        r=repo.update_run(r['runId'],lambda r:{**r,'state':{**r.get('state',{}),'outputKind':'paper_comparison'}})
        assert planning_options(r,QUESTION)['joint_reports'] is True
        for value in [0,None,True]:
            with pytest.raises(ValueError,match='Immutable'):
                repo.update_run(r['runId'],lambda current:{**current,'comparisonJointReportsContractVersion':value})
    finally:facade.shutdown()


def test_actual_synthesis_compiles_joint_report_and_preserves_all_other_targets():
    from services.deep_research.graph import make_synthesize_node
    cp,payload,ev,question=fixture();current=record()
    current.update(runId='r',question=question,comparisonPlanningContractVersion=2,comparisonJointReportsContractVersion=1)
    requirements=cp['requirements']
    current['state'].update(evidence=[ev],outputKind='paper_comparison',plan=[
        {'itemId':'facts','question':'mechanism','obligations':requirements[:1]},
        {'itemId':'judgement','question':'comparison','obligations':requirements[1:3]},
        {'itemId':'example','question':'one matched example','obligations':requirements[3:]}])
    before=deepcopy(current['state']['evidence']);sent=[]
    def update(rid,fn,**kwargs):
        nonlocal current
        current=fn(deepcopy(current));return deepcopy(current)
    def invoke(rid,node,prompt,options,**kwargs):
        assert node=='synthesize' and 'Joint answer targets' in prompt
        assert 'kind=reported' in prompt and 'ACROSS the whole answer' in prompt
        sent.append(prompt);return {'content':json.dumps(payload)}
    result=make_synthesize_node(invoke,update)({'run_id':current['runId']})
    assert not result.get('error_code') and len(sent)==1
    draft=current['state']['comparisonCellDraft']
    assert draft['jointReports'] is True and {'mechanism','fairness','choice'}<=set(draft['unresolvedObligationIds'])
    claims=current['state']['reportBody']['claims']
    assert len(claims)==1 and claims[0]['kind']=='reported' and claims[0]['evidenceRefs']==[ev['evidenceId']]
    assert current['state']['evidence']==before and not current['state'].get('verifiedReport')


def test_example_alone_does_not_pass_complete_question_audit():
    from services.deep_research.final_coverage import audit_final_answer
    from test_deep_research_comparison_audit import decode as decode_prompt
    from services.deep_research.structured_output import normalize
    cp,draft,c,ev,question=compiled();sent=[]
    def invoke(rid,node,prompt,options,**kwargs):
        data=decode_prompt(prompt);sent.append(data);rows=[]
        for obligation in data['requirements']:
            checks=[]
            for required in obligation['checks']:
                row={'checkId':required['checkId'],'status':'missing','bindings':[],
                     'reason':'The numerical example does not supply the requested mechanisms and choices.'}
                if required.get('responseType')=='limitation':row['limitSpans']=[]
                if required.get('processRequired'):row['processLinks']=[]
                checks.append(row)
            rows.append({'obligationId':obligation['obligationId'],'checks':checks})
        return normalize(node,{'content':json.dumps({'items':rows,'auditType':'answer_coherence','coherent':True,'issues':[]})},comparison_audit_envelope=True)
    plan=[{'obligations':cp['requirements']}]
    result=audit_final_answer('r',question,plan,[c],[ev],invoke,json.loads,request_contract=5,
        diagnostics=True,coherence=True,shared_decision_inputs=True,shared_evidence_context=True,
        consolidated_instructions=True,literal_limits=True,comparison_cells=metadata(draft),comparison_audit_envelope=True)
    assert len(sent)==1 and result['gaps']
    assert {'mechanism','fairness','choice'}<={gap['obligationId'] for gap in result['gaps']}
