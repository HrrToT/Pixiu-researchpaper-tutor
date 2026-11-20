from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.answer_locators import without_section_locators
from services.deep_research.completion_criteria import _identification_objects_present,completion_criteria_gaps
from services.deep_research.display_metadata import answer_display_metadata,display_metadata_digest,revalidate_display_metadata
from services.deep_research.coverage_binding_catalog import build_scoped,expand_scoped
from services.deep_research.access_disclosure import access_requirements
from services.deep_research.request_coverage import contract
from services.deep_research.final_coverage import audit_final_answer


@pytest.mark.parametrize('text,clean',[
 ('第5节中两个约束分别是什么','中两个约束分别是什么'),
 ('第4.5节的机制','的机制'),('第2章所述算法','所述算法'),
 ('In Section 5, identify 7 components',', identify 7 components'),
 ("Section 4.5's input is 7-dimensional",'input is 7-dimensional'),
])
def test_only_clear_locative_section_references_are_removed(text,clean):
 assert without_section_locators(text).strip()==clean


@pytest.mark.parametrize('text',['第5节','识别第5节的章节号','给出第5节中的编号',
 'Which section number is 5?','5个样本和7维向量','arXiv:2403.17888v3'])
def test_explicit_identity_requests_bare_identifiers_and_actual_numbers_stay(text):
 assert without_section_locators(text)==text


def items(question='第5节中两个约束分别是什么',answer='深度约束收拢交点，法线约束对齐盘面方向。'):
 c={'criterionId':'c','requirement':question,'responseType':'identification'}
 o={'obligationId':'o','question':question,'requestExcerpt':question,'purpose':'answer_requirement',
    'requiredSources':['p'],'completionCriteria':[c]}
 claim={'claimId':'answer','kind':'reported','text':answer,'conditions':{},'evidenceRefs':['e']}
 ev={'evidenceId':'e','quote':'Depth regularization concentrates intersections. Normals align with the depth-derived surface.',
     'sourceContext':'Depth regularization concentrates intersections. Normals align with the depth-derived surface.',
     'sourceKind':'arxiv','sourceWorkId':'p','sourceVersionId':'v','accessLevel':'fulltext'}
 verdict={'obligationId':'o','status':'covered','criteria':[{'criterionId':'c','responseType':'identification','status':'covered',
     'bindings':[{'claimId':'answer','field':'text','excerpt':answer}]}]}
 return c,o,claim,ev,verdict


def test_locator_policy_is_versioned_and_completion_revalidation_uses_it():
 c,o,claim,ev,v=items();plan=[{'obligations':[o]}]
 assert completion_criteria_gaps(plan,[claim],[v])
 old=answer_display_metadata([claim],[ev],task_sources=True,request_semantics=2)
 new=answer_display_metadata([claim],[ev],task_sources=True,request_semantics=2,identification_locators=True)
 assert not completion_criteria_gaps(plan,[claim],[v],display_metadata=new)
 assert completion_criteria_gaps(plan,[claim],[v],display_metadata=old)
 a=display_metadata_digest([claim],[ev],task_sources=True,request_semantics=2)
 b=display_metadata_digest([claim],[ev],task_sources=True,request_semantics=2,identification_locators=True)
 assert a!=b
 assert revalidate_display_metadata({'displayMetadataDigest':b},[claim],[ev],task_sources=True,request_semantics=2,identification_locators=True)=={'displayMetadataDigest':b}
 assert revalidate_display_metadata({'displayMetadataDigest':b},[claim],[ev],task_sources=True,request_semantics=2)['status']=='invalidated_display_metadata'


@pytest.mark.parametrize('question,answer',[
 ('识别第5节中的数值5和7','5'),('第5节中的7维向量是什么','向量的作用已说明'),
 ('请给出第5节的章节号','约束已说明'),
])
def test_actual_answer_objects_are_still_required(question,answer):
 c,o,_,_,_=items(question,answer)
 assert not _identification_objects_present(c,o,[{'excerpt':answer}],section_locators=True)


def test_scoped_catalog_excludes_access_field_for_science_but_preserves_explicit_access():
 _,o,claim,ev,_=items();access={'obligationId':'access','question':'标明实际引用的是全文片段还是摘要','purpose':'answer_requirement'}
 plan=[{'obligations':[o,access]}];reqs=contract(plan,'问题',whole_question_id=None,literal_request_dimensions=True)
 metadata=answer_display_metadata([claim],[ev],task_sources=True,request_semantics=2)
 perms=access_requirements(plan,joint=True,citation_access=True);before=deepcopy((reqs,metadata,plan,claim))
 packet=build_scoped([claim],metadata,reqs,perms)
 catalog=expand_scoped(packet)
 assert len(packet['catalogs'])==2
 assert all('sourceAccessSummary' not in row['fields'] for ch in catalog[0]['checks'] for row in ch['claims'])
 assert any('sourceAccessSummary' in row['fields'] for ch in catalog[1]['checks'] for row in ch['claims'])
 assert (reqs,metadata,plan,claim)==before


@pytest.mark.parametrize('bad_binding',[False,True])
def test_final_coverage_keeps_scientific_bindings_and_rejects_unrequested_metadata(bad_binding):
 _,o,claim,ev,_=items();question=o['question'];plan=[{'obligations':[o]}]
 full=plan+[{'obligations':[{'obligationId':'answer_scope','question':question}]}]
 required=contract(full,question,whole_question_id='answer_scope',literal_request_dimensions=True)
 response=[]
 for row in required:
  binding=[{'claimId':'answer','field':'text'}]
  if bad_binding and row['obligationId']=='answer_scope':binding.append({'claimId':'answer','field':'sourceAccessSummary'})
  response.append({'obligationId':row['obligationId'],'checks':[{'checkId':c['checkId'],'status':'covered',
   'bindings':binding,'reason':'Actual accepted prose identifies each constraint.'} for c in row['checks']]})
 invoke=Mock(return_value={'content':json.dumps(response)})
 result=audit_final_answer('run',question,plan,[claim],[ev],invoke,json.loads,request_contract=3,
  request_semantics=2,task_sources=True,binding_catalog=True,scoped_catalog=True,identification_locators=True,diagnostics=True)
 assert bool(result['gaps'])==bad_binding
 assert result['status']==('invalid_response' if bad_binding else 'checked')
 prompt=invoke.call_args.args[2];assert 'Available answer bindings by check:' in prompt
 catalog=expand_scoped(json.loads(prompt.split('Available answer bindings by check: ')[1].split('\n')[0]))
 assert all('sourceAccessSummary' not in c['fields'] for o in catalog for ch in o['checks'] for c in ch['claims'])
 invoke.assert_called_once()


@pytest.mark.parametrize('replacement',[None,True,0,2,'1'])
def test_locator_policy_is_server_owned_frozen_and_old_runs_are_not_migrated(tmp_path,replacement):
 from services.deep_research.repository import DeepResearchRepository
 from services.deep_research.facade import ResearchFacade
 repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
 try:
  r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'第5节中是什么',
    'identificationLocatorContractVersion':replacement},start_async=False)
  assert r['identificationLocatorContractVersion']==1
  old=deepcopy(r);old.update(runId='old',idempotencyKey='old');old.pop('identificationLocatorContractVersion')
  repo.create_run(old);before=repo.require_run('old')
  facade.create({'workspaceTaskId':'t','operationKey':'other','question':'解释问题'},start_async=False)
  assert repo.require_run('old')==before
  with pytest.raises(ValueError,match='Immutable'):
   repo.update_run(r['runId'],lambda x:{**x,'identificationLocatorContractVersion':replacement})
 finally:facade.shutdown()


@pytest.mark.parametrize('index',[True,-1,99,'0'])
def test_scoped_catalog_rejects_wrong_references(index):
 wire={'catalogs':[[{'claimId':'a','fields':['text']}]],'obligations':[
   {'obligationId':'o','checks':[{'checkId':'c','catalogIndex':index}]}]}
 with pytest.raises(ValueError):expand_scoped(wire)


def test_scoped_catalog_shares_identical_lists_without_sharing_check_permissions():
 _,o,claim,ev,_=items();plan=[{'obligations':[{**deepcopy(o),'obligationId':'o'+str(i)} for i in range(20)]}]
 reqs=contract(plan,'问题',whole_question_id=None,literal_request_dimensions=True)
 meta=answer_display_metadata([claim],[ev],task_sources=True,request_semantics=2)
 packet=build_scoped([claim],meta,reqs,{})
 expanded=expand_scoped(packet)
 assert len(packet['catalogs'])==1 and len(expanded)==20
 assert all(check['claims']==[{'claimId':'answer','fields':['text']}] for row in expanded for check in row['checks'])
 assert len(json.dumps(packet,ensure_ascii=False).encode())<len(json.dumps(expanded,ensure_ascii=False).encode())
