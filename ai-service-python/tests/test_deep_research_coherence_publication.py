from copy import deepcopy
from unittest.mock import Mock
import json
import pytest
from services.deep_research.answer_coherence import publication_release
from services.deep_research.final_coverage import audit_final_answer
from services.deep_research.graph import make_publish_node
from test_deep_research_answer_coherence import row
from test_deep_research_final_coverage import PLAN,CLAIMS,verdicts


@pytest.mark.parametrize('decision',['coherent','incoherent','absent','stale'])
def test_only_current_confirmed_whole_answer_is_released_without_changing_scientific_verdicts(decision):
    extra=[] if decision=='absent' else [row(decision!='incoherent')]
    audit=audit_final_answer('r','q',PLAN,CLAIMS,[],Mock(return_value={'content':json.dumps(verdicts()+extra)}),json.loads,coherence=True)
    if decision=='stale':audit['answerCoherence']['answerDigest']='old'
    record={'question':'q','answerCoherenceContractVersion':2,'state':{
        'plan':deepcopy(PLAN),'outputKind':'claim_verification','gaps':[],'evidence':[],
        'reportBody':{'claims':deepcopy(CLAIMS)},'verifiedReport':{
            'verifiedClaims':deepcopy(CLAIMS),'rejectedClaims':[],'answerCoverage':audit}}}
    def update(_,fn,**kw):
        nonlocal record
        record=fn(record);return record
    publish=Mock(return_value=({'publicationId':'p'},True))
    result=make_publish_node(publish,update)({'run_id':'r','report_version_id':'v','execution_epoch':0})
    payload=publish.call_args.kwargs['payload']
    assert record['state']['verifiedReport']['verifiedClaims']==CLAIMS
    if decision=='coherent':
        assert payload['claims']==CLAIMS and result['outcome']=='complete'
        assert record['state']['publicationCoherence']['status']=='released'
    else:
        assert payload['claims']==[] and result['outcome']=='inconclusive'
        assert CLAIMS[0]['text'] not in publish.call_args.kwargs['report_text']
        assert record['state']['publicationCoherence']['heldClaimIds']==['c']
        assert '暂未发布结论' in payload['limitations']
    again=make_publish_node(publish,update)({'run_id':'r','report_version_id':'v','execution_epoch':0})
    assert again['outcome']==result['outcome'] and publish.call_args.kwargs['payload']==payload


def test_publication_hold_never_selects_one_of_two_conflicting_statements_as_true():
    claims=[{'claimId':'a','text':'Unknown mechanism.','kind':'reported'},
            {'claimId':'b','text':'Known mechanism.','kind':'reported'}]
    from services.deep_research.answer_coherence import extract
    _,coherence=extract([{'auditType':'answer_coherence','coherent':False,'issues':[
        {'kind':'contradiction','bindings':[{'claimId':'a','field':'text'},{'claimId':'b','field':'text'}],
         'reason':'Unqualified absence conflicts with explanation.'}]}],'q',claims)
    before=deepcopy(claims);decision=publication_release({'answerCoherence':coherence},'q',claims)
    assert decision['status']=='held' and decision['heldClaimIds']==['a','b']
    assert claims==before
