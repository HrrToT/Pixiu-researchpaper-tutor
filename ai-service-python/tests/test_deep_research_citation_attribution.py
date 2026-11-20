from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.citation_presentation import normalize
from services.deep_research.contracts import DeepResearchError
from services.deep_research.prose_checks import leaks_internal_reference
from services.deep_research.repair import _parse_repair_response, repair_rejected
from test_deep_research_experiment_representation import prepare
from test_deep_research_shared_experiment_repair import inputs

ALIASES={'E1':'a','E2':'b'}
QUOTES={'E1':'A reports the actual intervention.','E2':'B describes the actual scene.'}


@pytest.mark.parametrize('value,expected',[
    ('该条件（E1/E2）尚未对齐。','该条件尚未对齐。'),
    ('NTC结构来自E1；场景来自E2。','NTC结构来自所引原文；场景来自所引原文。'),
    ('E1/E2提及新出现物体，但未给出具体帧索引。','所引原文提及新出现物体，但未给出具体帧索引。'),
    ('根据E1/E2选择该方法。','根据所引原文选择该方法。'),
    ('According to E1/E2, the scene is available.','According to the cited passage, the scene is available.'),
    ('E1 reports the setup.','the cited passage reports the setup.'),
    ('E1仅说明该场景可用，不能证明所选窗口合格。','所引原文仅说明该场景可用，不能证明所选窗口合格。'),
])
def test_explicit_own_attribution_preserves_assertions_refs_values_and_raw_input(value,expected):
    claim={'claimId':'c','kind':'proposal','text':value,'conditions':{'context':[value]},
        'evidenceRefs':['a','b'],'executionSpec':{'literal':'E1/E2','number':0.2}}
    before=deepcopy(claim)
    result,audit=normalize(claim,ALIASES,QUOTES,version=2)
    assert result['text']==expected and result['conditions']=={'context':[expected]}
    assert result['evidenceRefs']==claim['evidenceRefs'] and result['executionSpec']==claim['executionSpec']
    assert audit['originalText']==value and audit['originalConditions']==claim['conditions'] and claim==before
    assert not leaks_internal_reference(result,[])
    assert normalize(claim,ALIASES,QUOTES)[0]==claim  # Existing contract byte/meaning stable.


@pytest.mark.parametrize('value',[
    '来自E1/E9。','来自E2。','E1/E2提及设置。','公式根据 $E1$ 推导。',
    '`根据E1`','```\nE1 reports the setup\n```','根据E1+E2计算。','依据E1/E2计算比值。',
    'E1变量','未知来源P1指出。','根据E1_foo计算。','E10 reports another setup.',
])
def test_unknown_uncited_symbol_code_math_or_ambiguous_reference_stays_rejected(value):
    claim={'claimId':'c','text':value,'evidenceRefs':['a']}
    result,audit=normalize(claim,ALIASES,QUOTES,version=2)
    assert result==claim and audit is None


@pytest.mark.parametrize('value',['来自E1。','根据E1/E2计算。','该能量（E1/E2）变化。'])
def test_actual_source_symbols_are_preserved_even_in_apparent_citation_context(value):
    claim={'text':value,'evidenceRefs':['a','b']}
    assert normalize(claim,ALIASES,{**QUOTES,'E1':'The energy E1 is minimized; E2 is its constraint.'},version=2)==(claim,None)


def test_illegal_other_reference_cannot_partially_hide_in_mixed_group():
    claim={'text':'根据E1/E2/E99选择方法。','evidenceRefs':['a','b']}
    assert normalize(claim,ALIASES,QUOTES,version=2)==(claim,None)


@pytest.mark.parametrize('value',['依据E1/E2计算比值。','来自E1/E2的比率。','According to E1/E2 ratio, compare values.'])
def test_ambiguous_unquoted_math_is_preserved_even_when_all_labels_are_cited(value):
    claim={'text':value,'evidenceRefs':['a','b']}
    assert normalize(claim,ALIASES,QUOTES,version=2)==(claim,None)


@pytest.mark.parametrize('replacement',[None,True,'2',0,1,5])
def test_contract_is_server_owned_immutable_and_type_strict(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'runs.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        value,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Read a paper',
            'citationPresentationContractVersion':replacement,'deferStart':True},start_async=False)
        assert value['citationPresentationContractVersion']==4
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(value['runId'],lambda r:{**r,'citationPresentationContractVersion':replacement})
    finally:facade.shutdown()


def test_experimental_repair_uses_new_presentation_without_changing_request_or_permissions():
    old=prepare();new=prepare(citation_presentation_version=2)
    assert new['prompt']==old['prompt'] and new['allowed']==old['allowed']
    patch=[{'claimId':'groups','edits':[{'op':'add','path':'/conditions',
        'value':{'context':'该方法来自E1，尚未执行，不保证改善。'}}]}]
    response={'content':json.dumps(patch)};audit=[]
    legacy=_parse_repair_response(old,response,json.loads,strict_response=True)
    revised=_parse_repair_response(new,response,json.loads,strict_response=True,presentation_audit=audit)
    assert 'E1' in legacy[0]['conditions']['context']
    assert revised[0]['conditions']['context']=='该方法来自所引原文，尚未执行，不保证改善。'
    assert audit and revised[0]['executionSpec']==legacy[0]['executionSpec'] and not revised[0].get('verification')
    patch[0]['edits'].append({'op':'replace','path':'/evidenceRefs','value':['foreign']})
    assert _parse_repair_response(new,{'content':json.dumps(patch)},json.loads,strict_response=True)==[]


def test_unknown_pending_cannot_change_presentation_contract():
    report,checks,evidence=inputs();states=[]
    options=dict(experimental_intent=3,shared_experiment_schema=True,experimental_edits=True,
        experimental_diagnostics=True,experimental_nested_tables=True)
    invoke=Mock(side_effect=OSError('unknown'))
    with pytest.raises(OSError):
        repair_rejected(report,checks,evidence,'Q',Mock(),json.loads,**options,
            invoke_request=invoke,checkpoint=lambda s:states.append(deepcopy(s)))
    frozen=deepcopy(states[-1]);invoke.reset_mock()
    with pytest.raises(DeepResearchError,match='原始输入'):
        repair_rejected(report,checks,evidence,'Q',Mock(),json.loads,**options,
            citation_presentation_version=2,batch_state=frozen,invoke_request=invoke)
    invoke.assert_not_called();assert frozen==states[-1]


@pytest.mark.parametrize('version',[None,2])
def test_synthesis_normalizes_new_conditions_and_persists_separate_audit(version):
    from services.deep_research.graph import make_synthesize_node
    from test_deep_research_experiment_representation import wrapped_claims
    from test_deep_research_lean_planning import record,lean_basis
    from test_deep_research_experiment_planning import Store,response
    current=record();current['factualScopeContractVersion']=1
    if version is not None:current['citationPresentationContractVersion']=version
    body={'sections':[],'claims':wrapped_claims()}
    for claim in body['claims']:
        claim['evidenceRefs']=['E1'];claim['conditions']={'context':'该方法来自E1，尚未执行。'}
    raw=deepcopy(body);store=Store(current)
    result=make_synthesize_node(Mock(side_effect=[response(lean_basis()),response(body)]),store.update)({'run_id':'r'})
    assert 'error_code' not in result and body==raw
    saved=store.value['state']
    assert bool(saved['synthesisPresentationAudit']) is (version==2)
    assert all(c['conditions']['context']==('该方法来自所引原文，尚未执行。' if version==2 else '该方法来自E1，尚未执行。')
        for c in saved['reportBody']['claims'])
    assert all(not c.get('verification') for c in saved['reportBody']['claims'])
