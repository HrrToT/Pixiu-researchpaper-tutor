import json
from copy import deepcopy
from unittest.mock import Mock
import pytest
from services.deep_research.joint_answer_bindings import bindings_supported,without_character_limits,access_instruction
from services.deep_research.display_metadata import answer_display_metadata,revalidate_display_metadata,display_metadata_digest
from services.deep_research.completion_criteria import _identification_objects_present
from services.deep_research.request_semantics import normalize_access_requirements
from services.deep_research.final_coverage import audit_final_answer
from services.deep_research.request_coverage import contract

ACCESS='标明实际读到的是全文还是摘要'
QUESTION='用不超过300字说明压缩方法。'+ACCESS+'。'
CLAIMS=[{'claimId':'c','kind':'reported','text':'剪枝减少冗余高斯。','conditions':{},'evidenceRefs':['e']}]
EVIDENCE=[{'evidenceId':'e','quote':'Pruning removes redundant Gaussians.','sourceKind':'task_paper','accessLevel':'fulltext','sourceWorkId':'paper'}]


def test_only_response_length_directive_is_ignored_for_identified_objects():
    c={'responseType':'identification','requirement':'用不超过300字说明表3的30dB结果'}
    o={'question':c['requirement']};b=[{'excerpt':'表3结果为30dB'}]
    assert not _identification_objects_present(c,o,b)
    assert _identification_objects_present(c,o,b,format_limits=True)
    for wrong in ('表3结果','结果为30dB','表3结果为20dB'):
        assert not _identification_objects_present(c,o,[{'excerpt':wrong}],format_limits=True)
    assert '300字节' in without_character_limits('用不超过300字节保存')
    assert '300个高斯' in without_character_limits('最多300个高斯')


def test_joint_binding_needs_real_prose_label_own_citations_and_explicit_access_command():
    metadata=answer_display_metadata(CLAIMS,EVIDENCE,task_sources=True,request_semantics=2)
    known={'c':CLAIMS[0]};label={'claimId':'c','field':'sourceAccessSummary','excerpt':metadata['sourceAccessSummary']}
    prose={'claimId':'c','field':'text','excerpt':CLAIMS[0]['text']}
    assert bindings_supported([prose,label],known,metadata,QUESTION)
    assert not bindings_supported([label],known,metadata,QUESTION)
    assert not bindings_supported([prose,label],known,{**metadata,'requestSemanticsContractVersion':True},QUESTION)
    assert not bindings_supported([prose,label],known,metadata,'解释压缩方法')
    assert not bindings_supported([prose,label],known,metadata,'解释全文方法与摘要方法的差异')
    assert not bindings_supported([prose,{**label,'excerpt':'读完整篇了'}],known,metadata,QUESTION)
    assert not bindings_supported([prose,label],{'c':{**CLAIMS[0],'evidenceRefs':['unknown']}},metadata,QUESTION)
    assert not access_instruction('请解释引文“'+ACCESS+'”的措辞')


def test_unsolicited_access_proof_location_is_projected_only_in_new_version():
    plan=[{'obligations':[{'obligationId':'a','question':'实际读到的是全文还是摘要？',
        'purpose':'answer_requirement','requestExcerpt':ACCESS,'requiredSources':['p'],
        'completionCriteria':[{'criterionId':'x','responseType':'identification',
            'requirement':'明确说明所依据的材料是论文全文还是仅摘要，并指出该信息在材料中的体现。'}]}]}]
    assert normalize_access_requirements(plan,QUESTION)[1]==[]
    new,changes=normalize_access_requirements(plan,QUESTION,version=2)
    assert new[0]['obligations'][0]['completionCriteria'][0]['requirement']==ACCESS
    assert changes and new[0]['obligations'][0]['requiredSources']==['p']
    # If the person explicitly asks for extra evidence/science, don't erase it.
    mixed=deepcopy(plan);mixed[0]['obligations'][0]['requestExcerpt']=ACCESS+'并指出实验结果'
    assert normalize_access_requirements(mixed,QUESTION+'并指出实验结果',version=2)[1]==[]


@pytest.mark.parametrize('version',[0,2])
def test_real_fixed_check_shape_handles_joint_scope_without_science_metadata_substitution(version):
    plan=[{'obligations':[
        {'obligationId':'science','question':'用不超过300字说明表3的结果','completionCriteria':[
            {'criterionId':'s','requirement':'用不超过300字说明表3的结果','responseType':'identification'}]},
        {'obligationId':'access','question':ACCESS,'completionCriteria':[
            {'criterionId':'a','requirement':ACCESS,'responseType':'identification'}]}]}]
    claims=[{**CLAIMS[0],'text':'表3结果显示剪枝减少冗余高斯。'}]
    q='用不超过300字说明表3的结果。'+ACCESS+'。'
    full_plan=[*plan,{'obligations':[{'obligationId':'answer_scope','question':q}]}]
    rows=[]
    for o in contract(full_plan,q,whole_question_id='answer_scope',literal_request_dimensions=True):
        binding=[{'claimId':'c','field':'sourceAccessSummary'}] if o['obligationId']=='access' else [{'claimId':'c','field':'text'}]
        if o['obligationId']=='answer_scope':binding.append({'claimId':'c','field':'sourceAccessSummary'})
        rows.append({'obligationId':o['obligationId'],'checks':[
            {'checkId':c['checkId'],'status':'covered','bindings':binding,'reason':'The accepted prose answers content and the label identifies actual access.'} for c in o['checks']]})
    invoke=Mock(return_value={'content':json.dumps(rows)})
    result=audit_final_answer('r',q,plan,claims,EVIDENCE,invoke,json.loads,
        task_sources=True,request_contract=3,request_semantics=version)
    if version==2:assert result['status']=='checked' and not result['gaps']
    else:assert result['gaps']


def test_new_scope_requires_its_own_metadata_digest_before_publication():
    audit={'status':'checked','gaps':[]}
    assert revalidate_display_metadata(audit,CLAIMS,EVIDENCE,task_sources=True)==audit
    assert revalidate_display_metadata(audit,CLAIMS,EVIDENCE,task_sources=True,request_semantics=2)['status']=='invalidated_display_metadata'
    current={**audit,'displayMetadataDigest':display_metadata_digest(CLAIMS,EVIDENCE,task_sources=True,request_semantics=2)}
    assert revalidate_display_metadata(current,CLAIMS,EVIDENCE,task_sources=True,request_semantics=2)==current
