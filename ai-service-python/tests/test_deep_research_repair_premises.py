from copy import deepcopy
import pytest
from services.deep_research.repair_premises import required_premises
from services.deep_research.repair import _prepare_repair
from services.deep_research.contracts import BudgetExhaustedError


def fixture():
    evidence=[]
    for work in ('a','b'):
        for i in range(6):
            quote=('This is a substantive description of the method representation and implementation. '*28)+str(i)
            evidence.append({'evidenceId':work+str(i),'sourceWorkId':work,'sourceVersionId':work+'-v1',
                'ownerMaterialId':work,'contentHash':'hash-'+work,'accessLevel':'fulltext','quote':quote,
                'sourceContext':quote,'location':{'page':i+1,'offset':0},'obligationIds':['o'],
                'verification':{'literal':'passed'}})
    claim={'claimId':'c','kind':'inference','text':'未经支持的原始判断。','conditions':{},
           'evidenceRefs':[e['evidenceId'] for e in evidence],'obligationIds':['o']}
    requirements=[{'obligationId':'o','question':'这些片段能否比较显存用量','requiredSources':['a-v1','b-v1'],
        'completionCriteria':[{'criterionId':'q','requirement':'显存证据不足就说明无法比较','responseType':'limitation'}]}]
    return claim,evidence,requirements


def test_broad_unverified_refs_are_hints_each_permitted_version_keeps_an_anchor():
    claim,evidence,req=fixture();before=deepcopy((claim,evidence,req));allowed={'c':claim['evidenceRefs']}
    ids,audit=required_premises([claim],evidence,allowed,req)
    assert len(ids)==2
    assert {e['sourceVersionId'] for e in evidence if e['evidenceId'] in ids}=={'a-v1','b-v1'}
    assert ids<=set(allowed['c']) and audit['targets'][0]['originalEvidenceIds']==claim['evidenceRefs']
    assert audit['verification']=='unchecked_navigation' and (claim,evidence,req)==before


@pytest.mark.parametrize('mutation',['version','literal','permission','duplicate'])
def test_ineligible_candidates_cannot_become_required(mutation):
    claim,evidence,req=fixture();bad=deepcopy(evidence[0]);bad['evidenceId']='bad'
    if mutation=='version':bad['sourceVersionId']='a-v2'
    elif mutation=='literal':bad['verification']['literal']='unchecked'
    extras=[bad,bad] if mutation=='duplicate' else [bad]
    allowed={'c':claim['evidenceRefs']+([] if mutation=='permission' else ['bad'])}
    ids,_=required_premises([claim],[*extras,*evidence],allowed,req)
    assert 'bad' not in ids


def test_unbound_target_retains_legacy_original_source_protection():
    claim,evidence,req=fixture();claim['obligationIds']=[]
    ids,audit=required_premises([claim],evidence,{'c':claim['evidenceRefs']},req)
    assert ids==set(claim['evidenceRefs']) and audit['targets'][0]['mode']=='legacy_unbound'


def test_actual_preparation_fits_broad_draft_without_erasing_original_or_expanding_permissions():
    claim,evidence,req=fixture();report={'claims':[claim]};check={'accepted':[],'rejected':[{'claimId':'c','reason':'unsupported'}]}
    kwargs={'fact_redraft':True,'source_aware_redraft':True,'concise_factual':True,'compact_source_repair':True,
            'requirement_context':req,'claim_check':9}
    before=deepcopy((report,check,evidence))
    with pytest.raises(BudgetExhaustedError):
        _prepare_repair(report,check,evidence,'比较显存',**kwargs,factual_prompt_version=1)
    prepared=_prepare_repair(report,check,evidence,'比较显存',**kwargs,factual_prompt_version=2)
    assert len(prepared['prompt'].encode('utf8'))<=24000
    assert prepared['originals']['c']==claim
    assert set(prepared['allowed']['c'])<=set(claim['evidenceRefs'])
    assert {e['sourceVersionId'] for e in evidence if e['evidenceId'] in prepared['allowed']['c']}=={'a-v1','b-v1'}
    assert prepared['repairPremiseAudit']['targets'][0]['originalEvidenceIds']==claim['evidenceRefs']
    assert (report,check,evidence)==before


def test_previously_verified_target_retains_all_original_citations():
    claim,evidence,req=fixture()
    ids,audit=required_premises([claim],evidence,{'c':claim['evidenceRefs']},req,verified_target_ids=['c'])
    assert ids==set(claim['evidenceRefs'])
    assert audit['targets'][0]['mode']=='verified_citations'


def test_compiled_cost_dimension_navigates_processing_work_without_rewriting_frozen_goals():
    claim, ev, req = fixture()
    claim['evidenceRefs'] = ['a0']
    ev[0].update(quote='We fine-tune the compressed representation for 5,000 steps.',
                 sourceContext='We fine-tune the compressed representation for 5,000 steps.',
                 location={'section': 'Experimental Settings'})
    req[0].update(question='比较额外处理成本、存储、画质和速度。', completionCriteria=[])
    context={'sources':{'P1':{'workId':'a','versionId':'a-v1'}},
             'layout':[{'claimIds':['c'],'source':'P1','axisTitle':'额外处理成本'}]}
    before=deepcopy((claim,ev,req,context));allowed={'c':[e['evidenceId'] for e in ev if e['sourceWorkId']=='a']}
    ids,audit=required_premises([claim],ev,allowed,req,comparison_context=context)
    assert 'a0' in ids and ids<=set(allowed['c'])
    assert any(b['navigationRole']=='processing_cost' for b in audit['targets'][0]['navigationBundles'])
    assert (claim,ev,req,context)==before


def test_scoped_navigation_cannot_reassign_a_cell_to_another_source_version():
    claim,ev,req=fixture();claim['evidenceRefs']=['a0']
    context={'sources':{'P1':{'workId':'a','versionId':'a-v2'}},
             'layout':[{'claimIds':['c'],'source':'P1','axisTitle':'成本'}]}
    with pytest.raises(ValueError,match='sources'):
        required_premises([claim],ev,{'c':claim['evidenceRefs']},req,comparison_context=context)


@pytest.mark.parametrize('change', [None, 'abstract', 'unchecked', 'not_cited', 'not_allowed'])
def test_local_representation_repair_retains_cited_parameter_definition(change):
    claim, evidence, requirements = fixture()
    claim.update(text='优化各高斯的位置、不透明度和颜色。', evidenceRefs=['a0', 'a1'])
    evidence[0].update(quote='The 3D representation uses 3D Gaussians and optimizes position, α and view dependent color.',
                       location={'section': 'Method'})
    evidence[1].update(quote='The optimized properties include 3D position, opacity α, and anisotropic covariance.',
                       location={'section': 'Introduction'})
    evidence = [*evidence[:2]]
    requirements[0].update(question='比较表示方式和训练成本', requiredSources=['a-v1'])
    context = {'sources': {'P1': {'workId': 'a', 'versionId': 'a-v1'}},
               'layout': [{'claimIds': ['c'], 'source': 'P1', 'axisTitle': '表示与压缩机制'}]}
    allowed = {'c': ['a0', 'a1']}
    if change == 'abstract':
        evidence[1]['accessLevel'] = 'abstract'
    elif change == 'unchecked':
        evidence[1]['verification']['literal'] = 'unchecked'
    elif change == 'not_cited':
        claim['evidenceRefs'] = ['a0']
    elif change == 'not_allowed':
        allowed['c'] = ['a0']
    before = deepcopy((claim, evidence, allowed))
    old, _ = required_premises([claim], evidence, allowed, requirements, comparison_context=context)
    revised, audit = required_premises([claim], evidence, allowed, requirements, comparison_context=context,
                                       local_parameter_definitions=True)
    assert old == {'a0'}
    assert revised == ({'a0', 'a1'} if change is None else old)
    assert set(audit['targets'][0]['requiredEvidenceIds']) == revised
    bound, bound_audit = required_premises([claim], evidence, allowed, requirements, comparison_context=context,
                                           local_parameter_definitions=2)
    assert bound == revised
    assert bound_audit['targets'][0].get('opacityDefinitionEvidenceIds', []) == (['a1'] if change is None else [])
    assert (claim, evidence, allowed) == before


@pytest.mark.parametrize(('text', 'refs', 'expected'), [
    ('优化位置、透明度、协方差。', ['def'], False),
    ('透明度（opacity）用于合成。', ['def'], False),
    ('α是透明度。', ['def'], False),
    ('优化位置、不透明度、协方差。', ['other'], False),
    ('优化位置、不透明度、协方差。', ['def'], True),
    ('增加不透明度会降低透明度。', ['def'], True),
    ('不透明度为α，1 − α是透明度。', ['def'], True),
    ('查看视角覆盖如何影响渲染。', ['other'], True),
])
def test_opacity_repair_checks_only_the_bound_parameter(text, refs, expected):
    from services.deep_research.repair_premises import preserves_opacity_binding

    assert preserves_opacity_binding(text, refs, ['def']) is expected
