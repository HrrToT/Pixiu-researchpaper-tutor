from copy import deepcopy
from unittest.mock import Mock
import pytest
from services.deep_research.measurement_numbers import without_dimensional_labels
from services.deep_research.verification import make_evidence,precheck_claims,verify_claims


def pair(text,quote='The 2D disks align their normals with normals from the depth map.'):
 e=make_evidence({'workId':'p','versionId':'v','contentHash':'h','accessLevel':'fulltext'},quote,quote,location={'page':5},obligation_ids=['o'])
 c={'claimId':'c','text':text,'kind':'reported','evidenceRefs':[e['evidenceId']],'conditions':{},'detailLevel':'fulltext'}
 return c,e


@pytest.mark.parametrize('name',['二维盘','二维的圆盘','2维椭圆盘','三维盘片'])
def test_surface_dimensional_names_are_not_empirical_counts_only_in_new_version(name):
 c,e=pair(name+'的法线与深度图估计的法线对齐。');before=deepcopy((c,e))
 assert precheck_claims([c],[e],quantity_spelling_version=9)['rejected'][0]['reason']=='numeric_mismatch'
 assert not precheck_claims([c],[e],quantity_spelling_version=10)['rejected']
 semantic=Mock(return_value=[{'claimId':'c','status':'unresolved','reason':'Dimension identity must be checked against its own source'}])
 assert not verify_claims([c],[e],semantic,quantity_spelling_version=10)['accepted']
 semantic.assert_called_once();assert (c,e)==before


@pytest.mark.parametrize('text',['负二维盘','第二维盘','二维向量','2维特征','三维输出','二维盘有3个通道','二维盘是7维向量'])
def test_measured_dimensions_ordinals_signs_and_counts_are_not_erased(text):
 if text in ['二维盘有3个通道','二维盘是7维向量']:
  assert precheck_claims([pair(text)[0]],[pair(text)[1]],quantity_spelling_version=10)['rejected'][0]['reason']=='numeric_mismatch'
 else:
  assert without_dimensional_labels(text,surface_labels=True)==text


def test_source_dimensional_name_never_licenses_an_empirical_count():
 c,e=pair('用了2个样本。','这些二维盘与表面法线对齐。')
 assert precheck_claims([c],[e],quantity_spelling_version=10)['rejected'][0]['reason']=='numeric_mismatch'


def test_version_ten_retains_previous_enumeration_and_factor_rules():
 c,e=pair('三个要点：压缩表示；降低冗余；保留细节。')
 assert not precheck_claims([c],[e],quantity_spelling_version=10)['rejected']
 c,e=pair('模型压缩十五倍。')
 assert precheck_claims([c],[e],quantity_spelling_version=10)['rejected'][0]['reason']=='numeric_mismatch'


@pytest.mark.parametrize('replacement',[None,True,0,9,10,'10'])
def test_new_quantity_contract_remains_server_owned_and_immutable(tmp_path,replacement):
 from services.deep_research.repository import DeepResearchRepository
 from services.deep_research.facade import ResearchFacade
 repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
 try:
  run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'解释二维盘','quantitySpellingContractVersion':replacement},start_async=False)
  assert run['quantitySpellingContractVersion']==12
  with pytest.raises(ValueError,match='Immutable'):
   repo.update_run(run['runId'],lambda r:{**r,'quantitySpellingContractVersion':replacement})
 finally:facade.shutdown()
