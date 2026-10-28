from copy import deepcopy
from unittest.mock import Mock
import pytest

from services.deep_research.verification import verify_claims
from services.deep_research.table_bindings import validate_declared_references,REFERENCE_GUIDANCE
from test_deep_research_table_bindings import fixture


@pytest.mark.parametrize('patch',[
 {'rowNumber':0},{'rowNumber':'3'},{'rowNumber':True},{'groupIndex':2},
 {'value':'135'},{'metric':'PSNR'},{'evidenceId':'outside'},
])
def test_inference_label_cannot_hide_invalid_declared_source_cell(patch):
 ev,c=fixture();c['kind']='inference';c['tableBindings'][0].update(patch)
 before=deepcopy([ev,c]);checker=Mock(return_value=[{'claimId':'c','status':'passed'}])
 result=verify_claims([c],[ev],checker,table_references_version=1)
 assert result['rejected'] and not result['accepted'];checker.assert_not_called()
 assert 'availableTableReferences' in result['rejected'][0]
 assert [ev,c]==before
 # Legacy runs keep their old request/policy and are not retroactively changed.
 assert verify_claims([c],[ev],checker)['accepted']


def test_invalid_later_binding_cannot_hide_behind_first_valid_cell():
 ev,c=fixture();c['kind']='inference';c['tableBindings'][1]['rowNumber']=0
 assert validate_declared_references(c,[ev])=='unverified_table_cell'


def test_derived_quantity_is_not_misclassified_as_a_reported_cell_and_still_requires_semantics():
 ev,c=fixture();c.update(kind='inference',text='两组结果数值相差20 FPS；这是一次推算，不解释原因。')
 c['tableBindings']=[
  {'evidenceId':ev['evidenceId'],'rowNumber':3,'groupIndex':0,'metric':'FPS','value':'134'},
  {'evidenceId':ev['evidenceId'],'rowNumber':3,'groupIndex':1,'metric':'FPS','value':'154'}]
 assert validate_declared_references(c,[ev]) is None
 checker=Mock(return_value=[{'claimId':'c','status':'failed','reason':'Independent negative fixture'}])
 result=verify_claims([c],[ev],checker,table_references_version=1)
 assert result['rejected'][0]['reason']=='semantic_unresolved';checker.assert_called_once()
 checker.return_value=[{'claimId':'c','status':'passed'}]
 assert verify_claims([c],[ev],checker,table_references_version=1)['accepted']
 assert not verify_claims([c],[ev],table_references_version=1)['accepted']


@pytest.mark.parametrize('bindings',[None,'bad',{},[None]])
def test_malformed_declared_binding_container_is_not_accepted(bindings):
 ev,c=fixture();c.update(kind='inference',tableBindings=bindings)
 assert validate_declared_references(c,[ev])=='invalid_table_binding'


def test_qualitative_inference_without_cell_references_remains_semantically_checked():
 ev,c=fixture();c.update(kind='inference',text='需要限定这项结果的解释。');c.pop('tableBindings')
 check=Mock(return_value=[{'claimId':'c','status':'failed'}])
 assert verify_claims([c],[ev],check,table_references_version=1)['rejected'][0]['reason']=='semantic_unresolved'
 check.assert_called_once()


@pytest.mark.parametrize('kind',['proposal','suggestion','hypothesis'])
def test_unexecuted_choices_cannot_fabricate_declared_original_cell_references(kind):
 ev,c=fixture();c.update(kind=kind,text='建议设置目标速度20 FPS。')
 c['tableBindings'][0]['rowNumber']=0;check=Mock(return_value=[{'claimId':'c','status':'passed'}])
 assert verify_claims([c],[ev],check,table_references_version=1)['rejected'][0]['reason']=='unverified_table_cell'
 check.assert_not_called()
 # A proposed target is not a reported measurement and needs no fabricated binding.
 c['tableBindings']=[]
 assert verify_claims([c],[ev],check,table_references_version=1)['accepted']
 check.assert_called_once()


@pytest.mark.parametrize('replacement',[None,True,False,0,3,'1'])
def test_server_policy_is_owned_frozen_and_wired_for_both_passes(tmp_path,replacement):
 from services.deep_research.facade import ResearchFacade
 from services.deep_research.repository import DeepResearchRepository
 repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
 facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
 try:
  p,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'核对表格',
   'deferStart':True,'tableReferencesContractVersion':replacement},start_async=False)
  assert p['tableReferencesContractVersion']==2
  with pytest.raises(ValueError,match='Immutable'):
   repo.update_run(p['runId'],lambda r:{**r,'tableReferencesContractVersion':replacement})
  ev,c=fixture();c['kind']='inference';c['tableBindings'][0]['rowNumber']=0;checker=Mock()
  verifier=facade._get_verify_claims(p['runId'])
  for _ in range(2):
   assert verifier([c],[ev],checker)['rejected'][0]['reason']=='unverified_table_cell'
  checker.assert_not_called()
 finally:facade.shutdown()


def test_parser_row_feedback_is_aliased_inside_actual_repair_prompt_without_changing_original():
 from services.deep_research.repair import _prepare_repair
 ev,c=fixture();c['kind']='inference';c['tableBindings'][0]['rowNumber']=0
 checks=verify_claims([c],[ev],table_references_version=1);before=deepcopy(checks)
 prepared=_prepare_repair({'claims':[c]},checks,[ev],'核对这两项数值，200字以内',
  fact_redraft=True,concise_factual=True,declared_table_refs=True)
 assert REFERENCE_GUIDANCE in prepared['prompt']
 assert '"availableTableReferences":[{"evidenceId":"E1"' in prepared['prompt']
 assert '"rowNumber":3' in prepared['prompt'] and checks==before
 assert prepared['allowed']['c']==[ev['evidenceId']]
