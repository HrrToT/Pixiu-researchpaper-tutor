from copy import deepcopy
import hashlib
import pytest

from services.deep_research.indexed_section_premises import bundle
from services.deep_research.synthesis_evidence import order_premises


def fixture():
    sources=[];rows=[]
    for i,body in enumerate(['5 TRAINING\nDepth regularization introduction.',
                              'The depth loss concentrates intersection weights.',
                              'Normal alignment uses depth-gradient normals.'],10):
        text='Paper: Example\nSection: TRAINING\nContent:\n'+body
        sid=f'paper-v{"a"*16}-chunk-{i}';digest=hashlib.sha256(text.encode()).hexdigest()
        location={'page':5,'chunk':i,'section':'TRAINING'}
        sources.append({'sourceId':sid,'workId':'paper','ownerMaterialId':'paper','versionId':'v1',
            'contentHash':digest,'accessLevel':'fulltext','text':text,'location':location})
        rows.append({'evidenceId':f'e{i}','sourceId':sid,'sourceWorkId':'paper','ownerMaterialId':'paper',
            'sourceVersionId':'v1','contentHash':digest,'accessLevel':'fulltext','quote':body,
            'location':{**location,'sourcePassageStart':text.index(body),'sourcePassageEnd':len(text)},
            'verification':{'literal':'passed'},'obligationIds':['o']})
    return rows,sources


def test_separate_original_units_prioritized_without_fabricating_page_offsets():
    rows,sources=fixture();before=deepcopy((rows,sources))
    assert bundle(rows,sources,'paper',['5'])==rows
    assert (rows,sources)==before
    plan=[{'obligations':[{'obligationId':'o','question':'解释第5节','requiredSources':['paper']}]}]
    result,bundles=order_premises(list(reversed(rows)),plan,read_sources=sources,section_targets=['5'],indexed_sections=True)
    assert result==rows
    assert any(b['criterionId']=='requested_section' and b['evidenceIds']==['e10','e11','e12'] for b in bundles)
    _,legacy=order_premises(rows,plan,read_sources=sources,section_targets=['5'])
    assert not any(b['criterionId']=='requested_section' for b in legacy)


@pytest.mark.parametrize('change', [
    {'workId':'foreign'},{'ownerMaterialId':'foreign'},{'accessLevel':'abstract'},
    {'versionId':'foreign'},{'contentHash':'wrong'},{'sourceId':'forged'},
    {'location':{'chunk':11,'page':True,'section':'TRAINING'}},
    {'location':{'chunk':11,'page':8,'section':'TRAINING'}},
])
def test_invalid_intermediate_source_never_bridges_to_following_fragment(change):
    rows,sources=fixture();sources[1].update(change)
    assert bundle(rows,sources,'paper',['5'])==rows[:1]


@pytest.mark.parametrize('mutation', ['foreign_owner','wrong_quote','wrong_hash','missing_body','duplicate_unit'])
def test_only_complete_exact_owned_source_units_are_allocated(mutation):
    rows,sources=fixture()
    if mutation=='foreign_owner':rows[1]['ownerMaterialId']='foreign'
    if mutation=='wrong_quote':rows[1]['quote']='Invented.'
    if mutation=='wrong_hash':rows[1]['contentHash']='wrong'
    if mutation=='missing_body':rows[1]['location']['sourcePassageEnd']-=1;rows[1]['quote']=rows[1]['quote'][:-1]
    if mutation=='duplicate_unit':rows.append(deepcopy(rows[1]))
    assert bundle(rows,sources,'paper',['5'])==rows[:1]


def test_ambiguous_head_or_unrequested_section_does_not_allocate():
    rows,sources=fixture()
    assert bundle(rows,sources+[deepcopy(sources[0])],'paper',['5'])==[]
    assert bundle(rows,sources,'paper',['6'])==[]
    assert bundle(rows,sources,'foreign',['5'])==[]


def test_malformed_saved_inputs_cannot_fabricate_a_bundle():
    rows,sources=fixture()
    assert bundle([None,{'location':None}],sources,'paper',['5'])==[]
    assert bundle(rows,[None,{'location':'bad'},{'location':{},'sourceId':[]}],'paper',['5'])==[]
    assert bundle(rows,sources,None,['5'])==[]
