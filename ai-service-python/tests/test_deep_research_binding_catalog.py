from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.coverage_binding_catalog import build
from services.deep_research.final_coverage import audit_final_answer
from services.deep_research.display_metadata import answer_display_metadata
from services.deep_research.joint_answer_bindings import bindings_supported, access_instruction
from services.deep_research.request_coverage import contract

CLAIMS=[{'claimId':'c','kind':'reported','text':'剪枝减少冗余高斯。','conditions':{},'evidenceRefs':['e']}]
EVIDENCE=[{'evidenceId':'e','quote':'Pruning removes redundant Gaussians.','sourceKind':'task_paper',
           'accessLevel':'fulltext','sourceWorkId':'paper'}]
ACCESS='标明本次实际引用的是全文片段还是摘要'
QUESTION='说明压缩机制。'+ACCESS+'。'


def test_catalog_only_describes_real_fields_and_owned_access_without_mutation():
    rows=deepcopy(CLAIMS);metadata=answer_display_metadata(rows,EVIDENCE,task_sources=True)
    before=deepcopy((rows,metadata))
    assert build(rows,metadata)==[{'claimId':'c','fields':['text','sourceAccessSummary']}]
    assert (rows,metadata)==before
    rows[0]['conditions']={'dataset':'scene A'}
    assert build(rows,metadata)[0]['fields']==['text','conditions','sourceAccessSummary']
    rows[0]['evidenceRefs']=['foreign']
    assert 'sourceAccessSummary' not in build(rows,metadata)[0]['fields']
    assert build(rows+rows,metadata)==[]


def test_citation_access_is_versioned_and_cannot_turn_science_into_metadata():
    metadata=answer_display_metadata(CLAIMS,EVIDENCE,task_sources=True,request_semantics=2)
    new={**metadata,'answerBindingCatalogVersion':1}
    prose={'claimId':'c','field':'text','excerpt':CLAIMS[0]['text']}
    label={'claimId':'c','field':'sourceAccessSummary','excerpt':metadata['sourceAccessSummary']}
    assert access_instruction(QUESTION) is None
    assert access_instruction(QUESTION,citation_access=True)==ACCESS.replace('引用','依据')
    assert bindings_supported([prose,label],{'c':CLAIMS[0]},new,QUESTION)
    for bad in (metadata,{**new,'answerBindingCatalogVersion':True}):
        assert not bindings_supported([prose,label],{'c':CLAIMS[0]},bad,QUESTION)
    assert not bindings_supported([label],{'c':CLAIMS[0]},new,QUESTION)
    assert not bindings_supported([prose,label],{'c':CLAIMS[0]},new,'说明全文方法与摘要方法的区别')


@pytest.mark.parametrize('empty_binding',[False,True])
def test_actual_audit_advertises_catalog_but_does_not_remove_invalid_conditions(empty_binding):
    plan=[{'obligations':[{'obligationId':'science','question':'说明压缩机制'}]}]
    full=[*plan,{'obligations':[{'obligationId':'answer_scope','question':QUESTION}]}]
    response=[]
    for obligation in contract(full,QUESTION,whole_question_id='answer_scope',literal_request_dimensions=True):
        refs=[{'claimId':'c','field':'text'}]
        if obligation['obligationId']=='answer_scope':
            refs.append({'claimId':'c','field':'sourceAccessSummary'})
            if empty_binding:refs.append({'claimId':'c','field':'conditions'})
        response.append({'obligationId':obligation['obligationId'],'checks':[
            {'checkId':c['checkId'],'status':'covered','bindings':refs,'reason':'Actual scientific text and access label.'}
            for c in obligation['checks']]})
    invoke=Mock(return_value={'content':json.dumps(response)})
    result=audit_final_answer('r',QUESTION,plan,CLAIMS,EVIDENCE,invoke,json.loads,
        task_sources=True,request_semantics=2,request_contract=3,binding_catalog=True,diagnostics=True)
    assert ('answer_scope' in result.get('diagnosticErrors',[]))==empty_binding
    assert bool(result['gaps'])==empty_binding
    prompt=invoke.call_args.args[2]
    assert 'Available answer bindings:' in prompt
    catalog=json.loads(prompt.split('Available answer bindings: ')[1].split('\n')[0])
    assert catalog==[{'claimId':'c','fields':['text','sourceAccessSummary']}]
    invoke.assert_called_once()
