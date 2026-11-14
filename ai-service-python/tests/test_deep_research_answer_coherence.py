from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.answer_coherence import extract, revalidate, identity
from services.deep_research.final_coverage import audit_final_answer
from test_deep_research_final_coverage import PLAN,CLAIMS,verdicts


def row(coherent=True):
    return {'auditType':'answer_coherence','coherent':coherent,'issues':[] if coherent else [
        {'kind':'scope_ambiguity','bindings':[{'claimId':'c','field':'text'}],
         'reason':'The answer states incompatible unqualified scopes.'}]}


def test_joint_consistency_is_checked_in_the_existing_single_coverage_call():
    original=verdicts();invoke=Mock(return_value={'content':json.dumps(original+[row()])})
    audit=audit_final_answer('r','question',PLAN,CLAIMS,[],invoke,json.loads,coherence=True)
    assert audit['status']=='checked' and audit['gaps']==[]
    assert audit['answerCoherence']['coherent'] is True
    assert audit['verdicts']==original
    invoke.assert_called_once();assert invoke.call_args.args[1]=='verify_answer_coverage'
    assert invoke.call_args.kwargs=={'use_reserve':True}
    assert 'Also append EXACTLY ONE additional array row:' in invoke.call_args.args[2]


def test_covered_requirements_cannot_hide_an_incoherent_combined_answer():
    original=verdicts();before=deepcopy(original)
    audit=audit_final_answer('r','question',PLAN,CLAIMS,[],
        Mock(return_value={'content':json.dumps(original+[row(False)])}),json.loads,coherence=True)
    assert audit['status']=='checked' and audit['verdicts']==before
    assert audit['answerCoherence']['coherent'] is False
    assert len(audit['gaps'])==1 and audit['gaps'][0]['coherenceGap']
    assert revalidate(audit,'question',CLAIMS)==audit


@pytest.mark.parametrize('change',['absent','duplicate','false_without_issue','true_with_issue',
    'foreign','missing_field','metadata','duplicate_binding','wrong_kind','bool_as_int','mixed_excerpt'])
def test_malformed_consistency_decisions_fail_closed_without_reinterpreting_coverage(change):
    value=row(False);values=[value]
    if change=='absent':values=[]
    if change=='duplicate':values=[value,deepcopy(value)]
    if change=='false_without_issue':value['issues']=[]
    if change=='true_with_issue':value['coherent']=True
    if change=='foreign':value['issues'][0]['bindings'][0]['claimId']='foreign'
    if change=='missing_field':value['issues'][0]['bindings'][0]['field']='executionSpec'
    if change=='metadata':value['issues'][0]['bindings'][0]['field']='sourceAccessSummary'
    if change=='duplicate_binding':value['issues'][0]['bindings']*=2
    if change=='wrong_kind':value['issues'][0]['kind']='repetition'
    if change=='bool_as_int':value['coherent']=1
    if change=='mixed_excerpt':value['issues'][0]['bindings'][0]['excerpt']='invented'
    ordinary,audit=extract(verdicts()+values,'q',CLAIMS)
    assert ordinary==verdicts() and audit['status']=='invalid_response'
    checked=revalidate({'verdicts':ordinary,'gaps':[],'answerCoherence':audit},'q',CLAIMS)
    assert checked['answerCoherence']['status']=='invalid_response' and checked['gaps']


def test_modified_answer_or_question_cannot_inherit_a_successful_consistency_decision():
    _,value=extract([row()],'q',CLAIMS)
    audit={'verdicts':verdicts(),'gaps':[],'answerCoherence':value}
    changed=deepcopy(CLAIMS);changed[0]['text']='Different answer.'
    assert revalidate(audit,'q',changed)['answerCoherence']['status']=='invalidated'
    assert revalidate(audit,'different question',CLAIMS)['gaps']
    assert identity('q',CLAIMS)!=identity('q',changed)
    assert not revalidate(audit,'q',CLAIMS)['gaps']


def test_old_audits_and_empty_answers_do_not_create_extra_model_calls():
    send=Mock(return_value={'content':json.dumps(verdicts())})
    old=audit_final_answer('r','q',PLAN,CLAIMS,[],send,json.loads)
    assert 'answerCoherence' not in old and not old['gaps']
    missing=audit_final_answer('r','q',PLAN,CLAIMS,[],send,json.loads,coherence=True)
    assert missing['status']=='invalid_response' and missing['answerCoherence']['status']=='invalid_response' and missing['gaps']
    never=Mock();empty=audit_final_answer('r','q',PLAN,[],[],never,json.loads,coherence=True)
    never.assert_not_called();assert empty['gaps'] and empty['answerCoherence']['status']=='not_checked'


def test_actual_source_limited_absence_and_later_explanation_bind_both_existing_points():
    claims=[{'claimId':'c1','text':'所给证据未说明该约束对象。','kind':'inference'},
            {'claimId':'c3','text':'该约束对齐圆盘法线与深度估计法线。','kind':'inference'}]
    issue={'auditType':'answer_coherence','coherent':False,'issues':[
        {'kind':'scope_ambiguity','bindings':[{'claimId':'c1','field':'text'},{'claimId':'c3','field':'text'}],
         'reason':'Earlier unqualified evidence-absence wording conflicts with the later definition.'}]}
    before=deepcopy(claims);_,audit=extract([issue],'q',claims)
    assert audit['status']=='checked' and not audit['coherent'] and claims==before


def test_missing_coherence_metadata_does_not_trigger_a_paid_factual_rewrite():
    from services.deep_research.graph import make_verify_node
    record={'question':'q','answerCoherenceContractVersion':1,'state':{
        'plan':deepcopy(PLAN),'reportBody':{'claims':deepcopy(CLAIMS)},
        'evidence':[],'outputKind':'claim_verification','gaps':[]}}
    def update(_,fn,**kw):
        nonlocal record
        record=fn(record);return record
    invoke=Mock(return_value={'content':json.dumps(verdicts())})
    make_verify_node(lambda c,e,check:{'accepted':c,'rejected':[]},Mock(),update,invoke)({'run_id':'r'})
    invoke.assert_called_once()
    assert invoke.call_args.args[1]=='verify_answer_coverage'
    assert record['state']['verifiedReport']['verifiedClaims']==CLAIMS
    assert record['state']['verifiedReport']['answerCoverage']['status']=='invalid_response'


@pytest.mark.parametrize('coherent,outcome',[(True,'complete'),(False,'partial')])
def test_publication_cannot_promote_incoherent_answers_even_with_all_checks_covered(coherent,outcome):
    from services.deep_research.graph import make_publish_node
    audit=audit_final_answer('r','q',PLAN,CLAIMS,[],
        Mock(return_value={'content':json.dumps(verdicts()+[row(coherent)])}),json.loads,coherence=True)
    record={'question':'q','answerCoherenceContractVersion':1,'state':{
        'plan':deepcopy(PLAN),'outputKind':'claim_verification','gaps':[],'evidence':[],
        'reportBody':{'claims':deepcopy(CLAIMS)},'verifiedReport':{
            'verifiedClaims':deepcopy(CLAIMS),'rejectedClaims':[],'answerCoverage':audit}}}
    def update(_,fn,**kw):
        nonlocal record
        record=fn(record);return record
    publish=Mock(return_value=({'publicationId':'p'},True))
    result=make_publish_node(publish,update)({'run_id':'r','report_version_id':'v','execution_epoch':0})
    assert result['outcome']==outcome
    assert publish.call_args.kwargs['payload']['claims']==CLAIMS
