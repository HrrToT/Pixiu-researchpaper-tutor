from copy import deepcopy
import pytest

from services.deep_research.procedure_targets import score


def request(query):return {'role':'procedure','query':query}


def test_operation_must_match_requested_object_in_its_own_sentence():
    q=request('比较网格提取路径')
    assert score('We convert Gaussian parameters to unbiased depth maps.',q)==0
    assert score('We extract the mesh from the fused field.',q)>score('A mesh can contain holes.',q)>0
    assert score('We extract an image. A mesh is discussed elsewhere.',q)<score('We extract a mesh.',q)
    assert score('We extract mesh features.',{'role':'result','query':'网格提取'})==0
    assert score('We extract meshes.',request('模型存储大小'))==0


@pytest.mark.parametrize('query,good,bad',[
    ('如何提取点云','We construct a point cloud from the measurements.','We render normal maps.'),
    ('生成法线图的步骤','We render normal maps from planar surfaces.','We extract a mesh.'),
    ('depth map generation pipeline','We generate depth maps by integration.','We extract point clouds.'),
    ('feature extraction steps','We extract features from the image.','We construct meshes.'),
])
def test_other_requested_objects_are_not_replaced_with_a_mesh_specific_rule(query,good,bad):
    assert score(good,request(query))>0 and score(bad,request(query))==0


def test_target_ranking_preserves_source_eligibility_literal_text_and_legacy_order():
    from services.deep_research.reading_roles import premise_bundles
    from services.deep_research.verification import make_evidence
    sources=[{'workId':w,'versionId':w+'v1','contentHash':w,'accessLevel':'fulltext'} for w in ('a','b')]
    def row(source,text,i,passed=True):
        r=make_evidence(source,text,text,location={'page':i,'sectionRole':'method'},obligation_ids=['o'])
        if not passed:r['verification']['literal']='failed'
        return r
    rows=[row(sources[0],'We introduce our method to convert and transform 3D primitives into planar depth maps. Then we render them.',1),
          row(sources[0],'We extract the surface mesh from the reconstructed signed distance field.',2),
          row(sources[1],'We extract an excellent mesh using many steps.',3),
          row(sources[0],'We extract the final mesh directly.',4,False)]
    before=deepcopy(rows);o={'o':{'obligationId':'o','question':'网格提取路径',
        'requiredSources':['av1'],'completionCriteria':[{'criterionId':'c','requirement':'网格提取路径'}]}}
    legacy,_=premise_bundles(rows,o);explicit,_=premise_bundles(rows,o,procedure_targets=False)
    new,bundles=premise_bundles(rows,o,procedure_targets=True)
    assert legacy==explicit and legacy[0]['evidenceId']==rows[0]['evidenceId']
    assert new[0]==rows[1] and all(e['sourceWorkId']=='a' for e in new) and rows==before
    assert bundles[0]['evidenceIds']==[rows[1]['evidenceId']]
    with pytest.raises(ValueError):premise_bundles(rows,o,procedure_targets=1)
