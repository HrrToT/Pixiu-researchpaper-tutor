from copy import deepcopy
import json

import pytest

from services.deep_research.comparison_generation import enabled


@pytest.mark.parametrize('flag', [None, True, False, 0, '1', 1.0])
def test_only_exact_server_profile_selects_cell_generation(flag):
    r = {'comparisonCellsContractVersion': flag, 'authoredBodyContractVersion': 3,
         'scopeExpressionContractVersion': 5, 'factualPromptContractVersion': 3,
         'synthesisEvidenceContractVersion':6,'synthesisInputContractVersion':2,'draftValidationContractVersion':1,
         'state': {'outputKind': 'paper_comparison'}}
    assert not enabled(r)
    r['comparisonCellsContractVersion'] = 1
    assert enabled(r)
    r['state']['outputKind'] = 'experiment_design'
    assert not enabled(r)


def test_actual_synthesis_dispatches_cells_and_keeps_valid_points_on_normal_verification_path():
    from test_deep_research_factual_prompt import node_capture
    from services.deep_research.graph import make_synthesize_node
    _, _, original = node_capture(3)
    record = deepcopy(original)
    record.update(comparisonCellsContractVersion=1, authoredBodyContractVersion=3,
                  scopeExpressionContractVersion=5, draftValidationContractVersion=1,
                  synthesisInputContractVersion=2)
    before = deepcopy(record['state']['evidence']); sent = []
    def update(rid, fn, **kw):
        nonlocal record
        record = fn(deepcopy(record)); return deepcopy(record)
    def invoke(rid, node, prompt, options, **kw):
        assert node == 'synthesize' and kw.get('use_reserve') is True
        sent.append(prompt)
        cells = json.JSONDecoder().raw_decode(prompt.split(
            'Cell routing and citation permissions (metadata, not evidence):\n', 1)[1])[0]
        first_ref = cells[0]['evidenceIds'][0]
        points = []
        for index, cell in enumerate(cells):
            point = {'kind': 'reported', 'body': {'prose': {'text': '测量深度用于三维重建。', 'conditions': {}}},
                     'evidenceRefs': [first_ref], 'tableBindings': [], 'detailLevel': 'fulltext'}
            points.append({'cellId': cell['cellId'], 'claims': [point], 'unresolved': False})
        # Same alias can only support the first paper; the second cell must be isolated.
        return {'content': json.dumps({'cells': points, 'conclusions': []})}
    result = make_synthesize_node(invoke, update)({'run_id': 'r'})
    assert not result.get('error_code') and len(sent) == 1
    state = record['state']; draft = state['comparisonCellDraft']
    assert len(state['reportBody']['claims']) == 1
    assert state['reportBody']['claims'][0]['obligationIds'] == ['o']
    assert len(draft['errors']) == 1 and draft['unresolvedObligationIds'] == ['o']
    assert draft['verification'] == 'unchecked' and not state.get('verifiedReport')
    assert state['evidence'] == before
    assert all(ref.startswith('ev_') for ref in state['reportBody']['claims'][0]['evidenceRefs'])


def test_server_defaults_off_and_existing_run_cannot_switch_cell_protocol(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo = DeepResearchRepository(tmp_path / 'r.sqlite3'); repo.initialize()
    facade = ResearchFacade(repo, lambda **kw: None, llm_client=object())
    try:
        r, _ = facade.create({'workspaceTaskId': 't', 'operationKey': 'op', 'question': '比较',
                              'comparisonCellsContractVersion': 1}, start_async=False)
        assert type(r['comparisonCellsContractVersion']) is int and r['comparisonCellsContractVersion'] == 0
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(r['runId'], lambda r: {**r, 'comparisonCellsContractVersion': 1})
    finally:
        facade.shutdown()


def test_actual_synthesis_does_not_merge_versions_of_the_same_work():
    from test_deep_research_factual_prompt import node_capture
    from services.deep_research.graph import make_synthesize_node
    _,_,record=node_capture(3)
    record.update(comparisonCellsContractVersion=1,authoredBodyContractVersion=3,
                  scopeExpressionContractVersion=5,draftValidationContractVersion=1,
                  synthesisInputContractVersion=2)
    for e in record['state']['evidence']: e['sourceWorkId']='same-work'
    record['state']['plan'][0]['obligations'][0]['requiredSources']=['same-work']
    seen=[]
    def update(rid,fn,**kw):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    def invoke(rid,node,prompt,options,**kw):
        sources=json.JSONDecoder().raw_decode(prompt.split(
            'Source registry (P keys identify papers, never citations): ',1)[1])[0]
        assert len(sources)==2
        assert len({s['workId'] for s in sources.values()})==1
        assert len({s['versionId'] for s in sources.values()})==2
        seen.append(sources)
        return {'content':json.dumps({'cells':[],'conclusions':[]})}
    result=make_synthesize_node(invoke,update)({'run_id':'r'})
    assert not result.get('error_code') and len(seen)==1
    draft=record['state']['comparisonCellDraft']
    assert draft['sources']==seen[0]
    assert len(draft['layout'])==2 and all(c['unresolved'] for c in draft['layout'])


def test_actual_verifier_rejects_a_repair_that_changes_the_cell_paper_before_semantic_dispatch():
    from unittest.mock import Mock
    from services.deep_research.graph import make_verify_node
    claims=[{'claimId':'a','kind':'reported','text':'方法 A 的结果。','conditions':{},'evidenceRefs':['b-e']},
            {'claimId':'b','kind':'reported','text':'方法 B 的结果。','conditions':{},'evidenceRefs':['b-e']}]
    evidence=[{'evidenceId':'b-e','sourceWorkId':'B','sourceVersionId':'B-v1','quote':'B result.'}]
    draft={'sources':{'P1':{'workId':'A','versionId':'A-v1'},'P2':{'workId':'B','versionId':'B-v1'}},
           'layout':[{'source':'P1','claimIds':['a'],'obligationId':'mechanism','question':'机制'},
                     {'source':'P2','claimIds':['b'],'obligationId':'mechanism','question':'机制'}]}
    record={'question':'比较方法','comparisonCellsContractVersion':1,'authoredBodyContractVersion':3,
            'scopeExpressionContractVersion':5,'factualPromptContractVersion':3,
            'synthesisEvidenceContractVersion':6,'synthesisInputContractVersion':2,'draftValidationContractVersion':1,
            'state':{'outputKind':'paper_comparison','reportBody':{'sections':[],'claims':claims},
                     'evidence':evidence,'comparisonCellDraft':draft,'plan':[]}}
    def update(rid,fn,**kw):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    verifier=Mock(side_effect=lambda cs,ev,semantic:{'accepted':deepcopy(cs),'rejected':[]})
    make_verify_node(verifier,None,update)({'run_id':'r'})
    assert verifier.call_count==1
    assert [c['claimId'] for c in verifier.call_args.args[0]]==['b']
    result=record['state']['verifiedReport']
    assert [c['claimId'] for c in result['verifiedClaims']]==['b']
    assert result['rejectedClaims'][0]['reason']=='comparison_cell_source_mismatch'


def test_same_work_different_version_is_not_an_allowed_cell_edit():
    from services.deep_research.comparison_cells import partition_source_bound_claims
    draft={'sources':{'P1':{'workId':'A','versionId':'A-v1'}},
           'layout':[{'source':'P1','claimIds':['c']}]}
    claim={'claimId':'c','evidenceRefs':['e'],'kind':'reported','text':'A result.'}
    ev=[{'evidenceId':'e','sourceWorkId':'A','sourceVersionId':'A-v2'}]
    good,bad=partition_source_bound_claims([claim],draft,ev)
    assert not good and bad[0]['reason']=='comparison_cell_source_mismatch'


def test_server_can_select_an_isolated_rollout_without_a_client_override(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **kw:None,llm_client=object(),comparison_cells_version=1)
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'比较',
                            'comparisonCellsContractVersion':0,'factualReviewContractVersion':3},start_async=False)
        assert run['comparisonCellsContractVersion']==1
        assert run['factualReviewContractVersion']==4
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'comparisonCellsContractVersion':0})
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'factualReviewContractVersion':3})
    finally:facade.shutdown()


@pytest.mark.parametrize('bad',[True,None,'1',2])
def test_invalid_server_rollout_is_rejected_before_facade_execution(bad):
    from services.deep_research.facade import ResearchFacade
    with pytest.raises(ValueError,match='rollout'):
        ResearchFacade(None,lambda **kw:None,llm_client=object(),comparison_cells_version=bad)


def test_legacy_model_response_cannot_inject_cell_layout_metadata():
    from test_deep_research_factual_prompt import node_capture
    from services.deep_research.graph import make_synthesize_node
    _,_,record=node_capture(3)
    def update(rid,fn,**kw):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    def invoke(*args,**kw):
        return {'content':json.dumps({'sections':[],'claims':[],
            'comparisonCells':{'version':1,'layout':'model-injected','sources':{}}})}
    result=make_synthesize_node(invoke,update)({'run_id':'r'})
    assert not result.get('error_code')
    assert 'comparisonCells' not in record['state']['reportBody']
