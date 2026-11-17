from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.comparison_cells import plan_cells, compile_cells
from services.deep_research.comparison_wire import table_catalog, targets
from services.deep_research.authored_body import decode
from services.deep_research.verification import make_evidence, verify_claims
from test_deep_research_comparison_layout import fixture as layout_fixture, QUESTION


def fixture():
    requirements, sources, evidence = layout_fixture()
    for e in evidence:
        e['quote'] = 'Table row 8: Ours-30K | 134 | 41m33s'
        e['tableData'] = {'groups': [['Benchmark', ['FPS', 'Train']]],
                          'rows': [[7, 'Ours-7K', ['160', '6m25s']],
                                   [8, 'Ours-30K', ['134', '41m33s']]]}
    plan = plan_cells(requirements, sources, evidence, shared_axes=True, typed_roles=True,
                      joint_reports=True, question=QUESTION, fixed_slots=True, unified_answers=True)
    registry, _ = table_catalog(plan, {})
    ref = next(k for k, v in registry.items() if v['binding']['evidenceId']=='E1'
               and v['binding']['metric']=='FPS')
    point = {'kind': 'reported', 'body': {'prose': {'text': 'Ours-30K FPS 134。', 'conditions': {}}},
             'evidenceRefs': ['E1'], 'cellRefs': [ref], 'detailLevel': 'fulltext'}
    rows = [{'targetId': t['targetId'], 'obligationIds': [], 'point': None} for t in targets(plan)]
    rows[0].update(obligationIds=['method'], point=point)
    joint = next(row for row in rows if row['targetId']=='joint_fairness')
    joint.update(obligationIds=['fairness'], point=deepcopy(point), unresolved=False)
    return plan, {'answers': rows}, registry


def test_uniform_local_and_joint_answers_compile_exact_server_cells_without_approval():
    plan, payload, _ = fixture(); before = deepcopy((plan, payload))
    draft = compile_cells(payload, plan, max_claims=10)
    assert len(draft['report']['claims'])==2 and not draft['errors']
    assert not draft['answerWireAudit']['errors'] and not draft['answerWireAudit']['scientificApproval']
    for c in draft['report']['claims']:
        assert 'cellRefs' not in c
        assert c['tableBindings']==[{'evidenceId':'E1','rowNumber':8,'groupIndex':0,'metric':'FPS','value':'134'}]
    assert 'choice' in draft['unresolvedObligationIds'] and (plan, payload)==before


def test_catalog_only_exposes_quoted_rows_and_references_change_with_source_version():
    plan, _, registry = fixture(); before = deepcopy(plan)
    assert len(registry)==4 and all(v['binding']['rowNumber']==8 for v in registry.values())
    _, catalog = table_catalog(plan,{})
    assert all([r[0] for r in table['rows']]==[8] for table in catalog)
    assert table_catalog(plan,{})[0]==registry and plan==before
    plan['sources']['P1']['versionId']='a-v2'
    new,_=table_catalog(plan,{})
    assert not {k for k,v in new.items() if v['source']=='P1'} & {k for k,v in registry.items() if v['source']=='P1'}


@pytest.mark.parametrize('mutation',['unknown','uncited','manual_binding','duplicate_ref','prose_leak','wrong_goal','conflicting_null'])
def test_invalid_answer_is_isolated_and_never_silently_corrected(mutation):
    plan, payload, registry = fixture(); row=payload['answers'][0]; point=row['point']
    if mutation=='unknown': point['cellRefs']=['Vunknown']
    elif mutation=='uncited': point['cellRefs']=[k for k,v in registry.items() if v['source']=='P2'][:1]
    elif mutation=='manual_binding': point['tableBindings']=[{'rowNumber':7,'value':'134'}]
    elif mutation=='duplicate_ref': point['cellRefs']*=2
    elif mutation=='prose_leak': point['body']['prose']['text']=point['cellRefs'][0]
    elif mutation=='wrong_goal': row['obligationIds']=['foreign']
    else: row['unresolved']=True
    before=deepcopy(payload);draft=compile_cells(payload,plan,max_claims=10)
    assert draft['layout'][0]['unresolved'] and not draft['layout'][0]['claimIds']
    assert len(draft['report']['claims'])==1  # Unaffected joint answer still receives ordinary review.
    assert draft['answerWireAudit']['errors'] and payload==before


@pytest.mark.parametrize('mutation',['duplicate','foreign','old_envelope'])
def test_target_identity_cannot_be_guessed_or_replayed_as_a_different_wire(mutation):
    plan,payload,_=fixture()
    if mutation=='duplicate':payload['answers'].append(deepcopy(payload['answers'][0]))
    elif mutation=='foreign':payload['answers'][0]['targetId']='foreign'
    else:payload={'cells':[],'conclusions':[]}
    with pytest.raises(ValueError):compile_cells(payload,plan,max_claims=10)


def test_missing_targets_stay_unresolved_and_do_not_erase_other_answers():
    plan,payload,_=fixture();payload['answers']=payload['answers'][:1]
    draft=compile_cells(payload,plan,max_claims=10)
    assert len(draft['report']['claims'])==1
    assert any(e['reason']=='missing_answer_target' for e in draft['answerWireAudit']['errors'])
    assert {'fairness','choice'}<=set(draft['unresolvedObligationIds'])


def test_shared_packet_must_be_owned_by_the_citing_source():
    plan,_,_=fixture();packet=plan['evidence']['E1'].pop('tableData')
    plan['evidence']['E1']['tableDataRef']='T1'
    with pytest.raises(ValueError,match='source-local'):
        table_catalog(plan,{'T1':{'source':'P2','tableData':packet}})
    registry,_=table_catalog(plan,{'T1':{'source':'P1','tableData':packet}})
    assert any(v['binding']['evidenceId']=='E1' for v in registry.values())


def test_valid_table_reference_never_approves_invented_prose_values():
    plan,payload,_=fixture();payload['answers'][0]['point']['body']['prose']['text']='Ours-30K FPS 999。'
    draft=compile_cells(payload,plan,max_claims=10)
    claim=decode(draft['report']['claims'][0],reasoning=True)
    q=plan['evidence']['E1']['quote']
    ev=make_evidence({'workId':'a','versionId':'a-v1','contentHash':'hash','accessLevel':'fulltext'},
                     q,q,location={},obligation_ids=['method']);ev['evidenceId']='E1'
    ev['tableData']=plan['evidence']['E1']['tableData'];checker=Mock(return_value=[])
    result=verify_claims([claim],[ev],checker,table_references_version=4)
    assert not result['accepted'] and result['rejected']
    checker.assert_not_called()


@pytest.mark.parametrize('text,normalizes',[
    ('训练时间41分33秒。', True), ('训练时间41 minutes 33 seconds。', True),
    ('训练时间41分34秒。', False), ('训练时间2433秒。', False), ('训练时间41米33秒。', False)])
def test_duration_spelling_requires_the_exact_whole_bound_sequence(text, normalizes):
    from services.deep_research.table_bindings import normalize_bound_duration_spelling
    plan,payload,registry=fixture()
    ref=next(k for k,v in registry.items() if v['binding']['evidenceId']=='E1' and v['binding']['metric']=='Train')
    point=payload['answers'][0]['point'];point['cellRefs']=[ref];point['body']['prose']['text']=text
    claim=decode(compile_cells(payload,plan,max_claims=10)['report']['claims'][0],reasoning=True)
    q=plan['evidence']['E1']['quote']
    e=make_evidence({'workId':'a','versionId':'a-v1','contentHash':'hash','accessLevel':'fulltext'},
                    q,q,location={},obligation_ids=['method']);e.update(evidenceId='E1',tableData=plan['evidence']['E1']['tableData'])
    normalized=normalize_bound_duration_spelling(text,claim,[e])
    assert ('41m33s' in normalized)==normalizes
    claim['tableBindings'][0]['rowNumber']=7
    assert normalize_bound_duration_spelling(text,claim,[e])==text


def test_duration_equivalence_only_reaches_independent_review_in_new_policy():
    from services.deep_research.verification import precheck_claims
    plan,payload,registry=fixture()
    ref=next(k for k,v in registry.items() if v['binding']['evidenceId']=='E1' and v['binding']['metric']=='Train')
    point=payload['answers'][0]['point'];point['cellRefs']=[ref]
    point['body']['prose']['text']='Benchmark上的Ours-30K训练时间41分33秒。'
    claim=decode(compile_cells(payload,plan,max_claims=10)['report']['claims'][0],reasoning=True)
    q=plan['evidence']['E1']['quote']
    e=make_evidence({'workId':'a','versionId':'a-v1','contentHash':'hash','accessLevel':'fulltext'},
                    q,q,location={},obligation_ids=['method']);e.update(evidenceId='E1',tableData=plan['evidence']['E1']['tableData'])
    kw={'table_references_version':4,'quantity_spelling_version':5}
    assert precheck_claims([claim],[e],**kw)['rejected'][0]['reason']=='numeric_mismatch'
    assert precheck_claims([claim],[e],bound_duration_spelling=True,**kw)['candidates']
    checker=Mock(return_value=[])
    result=verify_claims([claim],[e],checker,bound_duration_spelling=True,**kw)
    assert checker.call_count==1 and not result['accepted']  # No semantic verdict, no publication.
    claim['tableBindings'][0]['rowNumber']=7
    assert precheck_claims([claim],[e],bound_duration_spelling=True,**kw)['rejected']


def test_facade_selects_duration_policy_only_for_new_comparison_run(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    plan,payload,registry=fixture()
    ref=next(k for k,v in registry.items() if v['binding']['evidenceId']=='E1' and v['binding']['metric']=='Train')
    payload['answers'][0]['point'].update(cellRefs=[ref],body={'prose':{
        'text':'Benchmark上的Ours-30K训练时间41分33秒。','conditions':{}}})
    claim=decode(compile_cells(payload,plan,max_claims=10)['report']['claims'][0],reasoning=True)
    q=plan['evidence']['E1']['quote']
    e=make_evidence({'workId':'a','versionId':'a-v1','contentHash':'hash','accessLevel':'fulltext'},
                    q,q,location={},obligation_ids=['method']);e.update(evidenceId='E1',tableData=plan['evidence']['E1']['tableData'])
    repo=DeepResearchRepository(tmp_path/'unit-policy.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object(),comparison_cells_version=1,comparison_review_batch_version=1)
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':QUESTION,'deferStart':True},start_async=False)
        assert r['comparisonPlanningContractVersion']==4
        old={**r,'runId':'old','taskId':'old','idempotencyKey':'old','comparisonPlanningContractVersion':3}
        repo.create_run(old)
        check=Mock(return_value=[])
        assert not facade._get_verify_claims('old')([claim],[e],check)['accepted']
        check.assert_not_called()
        assert not facade._get_verify_claims(r['runId'])([claim],[e],check)['accepted']
        check.assert_called_once()  # Only reaches independent review; still not accepted.
    finally:facade.shutdown()


def test_real_synthesis_node_compiles_uniform_wire_and_authors_for_reader_once(tmp_path):
    from services.deep_research.graph import make_synthesize_node
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.shared_strings import unpack
    from services.deep_research.nested_tables import unpack as untables
    from test_deep_research_comparison_intent import record
    plan,_,_=fixture();r=record()
    r.update(runId='wire-r',taskId='wire-t',idempotencyKey='wire-k',status='running',
             question=QUESTION+'向新手解释。',comparisonPlanningContractVersion=4,
             comparisonReviewBatchContractVersion=2,comparisonJointReportsContractVersion=3,
             audienceRewriteContractVersion=9,audienceMappedSourceContractVersion=5,audienceFirstContractVersion=1,
             materials=[{'materialId':v['workId'],'title':v['title']} for v in plan['sources'].values()])
    ev=[]
    for wire in plan['evidence'].values():
        owner=plan['sources'][wire['source']]
        q=wire['quote'];e=make_evidence({**owner,'contentHash':'hash','accessLevel':'fulltext'},
                                       q,q,location={},obligation_ids=wire['obligations'])
        e['tableData']=wire['tableData'];ev.append(e)
    r['state'].update(outputKind='paper_comparison',plan=[{'itemId':'p','obligations':plan['requirements']}],evidence=ev)
    repo=DeepResearchRepository(tmp_path/'wire.sqlite3');repo.initialize();repo.create_run(r)
    sent=[]
    def update(rid,fn,**kw):return repo.update_run(rid,fn,**kw)
    def invoke(rid,node,prompt,options,**kw):
        assert node=='synthesize'  # No separate audience rewrite of the same comparison.
        sent.append(prompt)
        packet=json.JSONDecoder().raw_decode(prompt.split('Exact question obligations, source permissions, unchanged quotations/context, and visible typed cells:\n',1)[1])[0]
        data=untables(unpack(packet)) if set(packet)=={'strings','value'} else packet
        answers=[{'targetId':t['targetId'],'obligationIds':[],'point':None} for t in data['targets']]
        table=data['tableCatalog'][0];ref=table['rows'][0][2][0][0]
        answers[0].update(obligationIds=['method'],point={'kind':'reported',
            'body':{'prose':{'text':'Ours-30K FPS 134。','conditions':{}}},
            'evidenceRefs':[table['evidenceId']],'cellRefs':[ref],'detailLevel':'fulltext'})
        return {'content':json.dumps({'answers':answers}),'finishReason':'stop'}
    result=make_synthesize_node(invoke,update)({'run_id':'wire-r'})
    saved=repo.require_run('wire-r')['state']
    assert 'report_version_id' in result and len(sent)==1
    assert 'requested reader in this FIRST draft' in sent[0]
    assert saved['comparisonAuthoring']['readerExpression']=='first_draft'
    assert len(saved['reportBody']['claims'])==1 and 'audienceRewrite' not in saved
    assert saved['reportBody']['claims'][0]['tableBindings'][0]['rowNumber']==8
    assert not saved.get('verifiedReport')
