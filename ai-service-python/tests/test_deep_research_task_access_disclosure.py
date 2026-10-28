import json
from copy import deepcopy
from unittest.mock import Mock
import pytest

from services.deep_research.access_disclosure import access_only,access_requirements
from services.deep_research.display_metadata import answer_display_metadata,display_metadata_digest,revalidate_display_metadata
from services.deep_research.reporting import render_report,conversation_summary,visible_answer_character_count
from services.deep_research.coverage_references import resolve_coverage_references
from services.deep_research.completion_criteria import completion_criteria_gaps,invalid_criterion_reviews,revalidate_completion_audit
from services.deep_research.answer_coverage import answer_coverage_gaps
from services.deep_research.final_coverage import audit_final_answer

QUESTION='标明实际读到的是全文还是摘要。'
CLAIMS=[{'claimId':'c','kind':'reported','text':'剪枝减少冗余高斯。','conditions':{},'evidenceRefs':['e']}]
EVIDENCE=[{'evidenceId':'e','quote':'Pruning removes redundant Gaussians.','sourceContext':{},
    'sourceKind':'task_paper','sourceWorkId':'paper','sourceVersionId':'v','accessLevel':'fulltext'}]
PLAN=[{'obligations':[{'obligationId':'o','question':QUESTION,'completionCriteria':[
    {'criterionId':'access','requirement':'根据材料内容判断并明确说明是全文还是摘要。','responseType':'identification'}]}]}]


def verdict(key='o'):
    b=[{'claimId':'c','field':'sourceAccessSummary'}]
    return {'obligationId':key,'status':'covered','bindings':deepcopy(b),
        'criteria':[{'criterionId':'access','responseType':'identification','status':'covered','bindings':deepcopy(b)}] if key=='o' else [],
        'aspects':[{'aspectId':'access','requirement':QUESTION,'status':'covered',
            'basis':{'kind':'source_metadata','evidenceId':'e','field':'accessLevel','value':'fulltext','requestExcerpt':QUESTION},
            'bindings':deepcopy(b)}]}


@pytest.mark.parametrize('request_contract',[False,3])
def test_task_label_is_shared_by_report_summary_count_and_coverage_without_mutation(request_contract):
    original=deepcopy((CLAIMS,EVIDENCE));metadata=answer_display_metadata(CLAIMS,EVIDENCE,task_sources=True)
    label='本回答引用：全文片段。'
    assert metadata['sourceAccessSummary']==label
    assert answer_display_metadata(CLAIMS,EVIDENCE)=={}
    payload={'claims':CLAIMS,'evidence':EVIDENCE,'presentationVersion':4,'characterLimit':300}
    assert render_report(payload).startswith(label)
    assert not render_report({**payload,'presentationVersion':3}).startswith(label)
    assert conversation_summary(CLAIMS,'complete',evidence=EVIDENCE,presentation_version=4).startswith(label)
    assert visible_answer_character_count(payload)-visible_answer_character_count({**payload,'presentationVersion':3})==len(label)
    reply=[verdict(),verdict('answer_scope')]
    if request_contract:
        from services.deep_research.request_coverage import contract
        plan=[*PLAN,{'obligations':[{'obligationId':'answer_scope','question':QUESTION}]}]
        reply=[{'obligationId':o['obligationId'],'checks':[
            {'checkId':c['checkId'],'status':'covered','bindings':[{'claimId':'c','field':'sourceAccessSummary'}],
             'reason':'The server label identifies the actual access.'} for c in o['checks']]}
            for o in contract(plan,QUESTION,whole_question_id='answer_scope',literal_request_dimensions=True)]
    call=Mock(return_value={'content':json.dumps(reply)})
    result=audit_final_answer('r',QUESTION,PLAN,CLAIMS,EVIDENCE,call,json.loads,task_sources=True,request_contract=request_contract)
    assert result['status']=='checked' and result['gaps']==[]
    assert 'sourceAccessSummary' in call.call_args.args[2]
    assert revalidate_completion_audit(PLAN,CLAIMS,result,display_metadata=metadata)==result
    assert revalidate_display_metadata(result,CLAIMS,EVIDENCE,task_sources=True)==result
    assert (CLAIMS,EVIDENCE)==original


@pytest.mark.parametrize('level,label',[('abstract','摘要'),('fulltext','全文片段')])
def test_access_is_from_cited_records_not_claim_authored_disclosure(level,label):
    evidence=[{**EVIDENCE[0],'accessLevel':level}]
    claims=[{**CLAIMS[0],'sourceAccessSummary':'我读完整篇论文了','detailLevel':'fulltext'}]
    assert answer_display_metadata(claims,evidence,task_sources=True)['sourceAccessSummary']=='本回答引用：'+label+'。'
    assert answer_display_metadata(claims,[],task_sources=True)=={}
    assert answer_display_metadata([{**claims[0],'evidenceRefs':[]}],evidence,task_sources=True)=={}


@pytest.mark.parametrize('requirement',[
    '说明全文的方法和摘要的区别','标明全文实验结果是否优于摘要中的方法',
    '标明实际读到的是全文还是摘要并解释压缩机制',
    '根据材料判断方法是否正确','说明三个压缩环节',
])
def test_scientific_or_mixed_requirements_cannot_use_access_only_path(requirement):
    assert not access_only(requirement)
    plan=deepcopy(PLAN);plan[0]['obligations'][0]['question']=requirement
    plan[0]['obligations'][0]['completionCriteria'][0]['requirement']=requirement
    metadata=answer_display_metadata(CLAIMS,EVIDENCE,task_sources=True)
    rows=resolve_coverage_references([verdict()],CLAIMS,EVIDENCE,display_metadata=metadata,access_requirements=access_requirements(plan))
    assert completion_criteria_gaps(plan,CLAIMS,rows,display_metadata=metadata)
    assert answer_coverage_gaps(plan,CLAIMS,rows,display_metadata=metadata)


def test_legacy_criteria_do_not_gain_metadata_bindings_and_changed_access_invalidates_resume():
    metadata=answer_display_metadata(CLAIMS,EVIDENCE,task_sources=True)
    rows=resolve_coverage_references([verdict()],CLAIMS,EVIDENCE,display_metadata=metadata)
    assert invalid_criterion_reviews(PLAN,CLAIMS,rows)
    audit={'status':'checked','gaps':[],'displayMetadataDigest':display_metadata_digest(CLAIMS,EVIDENCE,task_sources=True)}
    changed=[{**EVIDENCE[0],'accessLevel':'abstract'}]
    assert revalidate_display_metadata(audit,CLAIMS,changed,task_sources=True)['status']=='invalidated_display_metadata'
    assert revalidate_display_metadata(audit,CLAIMS,EVIDENCE)['status']=='invalidated_display_metadata'


@pytest.mark.parametrize('change',['missing_record','unknown_level','uncited_claim','changed_kind','wrong_label'])
def test_access_criteria_require_exact_label_and_own_authoritative_citations(change):
    metadata=answer_display_metadata(CLAIMS,EVIDENCE,task_sources=True)
    claims=deepcopy(CLAIMS)
    rows=resolve_coverage_references([verdict()],claims,EVIDENCE,display_metadata=metadata,access_requirements=access_requirements(PLAN))
    if change=='missing_record':metadata['sourceAccessRecords']={}
    elif change=='unknown_level':metadata['sourceAccessRecords']['e']='unknown'
    elif change=='uncited_claim':claims[0]['evidenceRefs']=['other']
    elif change=='changed_kind':metadata['taskSourceAccessContractVersion']=True
    else:metadata['sourceAccessSummary']='已经读完整篇论文'
    assert completion_criteria_gaps(PLAN,claims,rows,display_metadata=metadata)
    assert answer_coverage_gaps(PLAN,claims,rows,display_metadata=metadata)


def test_actual_saved_access_requirement_is_supported_without_treating_science_as_metadata():
    assert access_only('实际阅读的材料是全文还是摘要？')
    assert access_only('明确说明所依据的材料是论文全文还是摘要')
    assert not access_only('说明所依据的论文方法如何改变压缩率')


@pytest.mark.parametrize('bad_id',[[],{},None])
def test_malformed_review_identities_are_rejected_without_crashing(bad_id):
    metadata=answer_display_metadata(CLAIMS,EVIDENCE,task_sources=True)
    row=verdict();row['criteria'][0]['criterionId']=bad_id
    rows=resolve_coverage_references([row],CLAIMS,EVIDENCE,display_metadata=metadata,access_requirements=access_requirements(PLAN))
    assert invalid_criterion_reviews(PLAN,CLAIMS,rows,display_metadata=metadata)
    row['obligationId']=bad_id
    resolve_coverage_references([row],CLAIMS,EVIDENCE,display_metadata=metadata,access_requirements=access_requirements(PLAN))
