"""Target prose navigation never grants scientific numeric or source permission."""
from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.review_target_structure import view
from services.deep_research.review_diagnostics import bind
from test_deep_research_factual_decision import checker,evidence,response,target

TEXT='先定义输入。然后计算更新。最后说明边界。'


def case(reason='前三个分句由引文支持，但最后一个分句不成立。'):
    claim={**target(),'text':TEXT};ev=evidence();ev[0]['quote']='A bounded source observation.'
    return {'claimId':'c','status':'failed','reason':reason,'diagnosticFacts':[]},claim,ev


@pytest.mark.parametrize(('reason', 'valid_cell', 'locator', 'unbound_numbers'), [
    ('The tableBindings correctly reference E4 rows 9 and 10.', True, True, 0),
    ('The tableBindings correctly reference E4 rows 9 and 10.', False, False, 2),
    ('The tableBindings reference E3 rows 9 and 10.', True, False, 2),
    ('The tableBindings reference E4 rows 9 and 11.', True, False, 2),
    ('The tableBindings reference E4 rows 9 and 10 FPS.', True, False, 2),
    ('The tableBindings reference E4 rows 9 and 10. Training took 9 seconds.', True, True, 1),
])
def test_only_exact_cited_table_addresses_are_excluded_from_review_numbers(reason, valid_cell, locator, unbound_numbers):
    verdict, claim, ev = case(reason)
    eid = ev[0]['evidenceId']
    ev[0]['quote'] = 'Table row 9: Baseline | 144\nTable row 10: Variant | 237'
    ev[0]['tableData'] = {'groups': [['Benchmark', ['FPS']]],
                         'rows': [[9, 'Baseline', ['144']], [10, 'Variant', ['237']]]}
    claim['tableBindings'] = [
        {'evidenceId': eid, 'rowNumber': row, 'groupIndex': 0, 'metric': 'FPS', 'value': value}
        for row, value in ((9, '144'), (10, '237' if valid_cell else '238'))
    ]
    result = bind(verdict, claim, ev, {'E4': eid}, target_structure=True)
    audit = result['reviewDiagnosticAudit']
    assert audit['unboundNewNumberCount'] == unbound_numbers
    assert bool(audit['targetStructureReferences']) is locator
    if locator:
        reference, = audit['targetStructureReferences']
        assert reference['evidenceId'] == eid and reference['rowNumbers'] == [9, 10]
    assert result['status'] == 'failed'  # Navigation never reverses a failed scientific decision.


@pytest.mark.parametrize('reference',['前三个分句','前3个分句','第3句','最后一个分句','后两句','first three clauses','first 3 sentences','last one sentence'])
def test_available_target_navigation_is_not_new_source_measurement(reference):
    verdict,claim,ev=case(reference+' does not establish this target.');before=deepcopy((verdict,claim,ev))
    old=bind(verdict,claim,ev);new=bind(verdict,claim,ev,target_structure=True)
    assert new['reviewDiagnosticAudit']['errors']==[] and new['status']=='failed' and new['reason']==verdict['reason']
    refs=new['reviewDiagnosticAudit']['targetStructureReferences'];assert len(refs)==1 and refs[0]['text']==reference
    assert (verdict,claim,ev)==before


@pytest.mark.parametrize('reason',['第四句不成立。','前99个分句不成立。','first four sentences fail.','前0句不成立。',
    '论文前三个分句证明结论。','原文第三句证明结论。',"the paper first three sentences prove it.",
    'first three sentences of the paper prove it.','算法第3行使用参数。','第三种方法更快。','进行了3次实验。','前三个数据集更好。',
    'β2=0.001 is correct.','The value is 3.2%.'])
def test_source_locations_out_of_range_and_scientific_values_remain_checked(reason):
    verdict,claim,ev=case(reason);old=bind(verdict,claim,ev);result=bind(verdict,claim,ev,target_structure=True)
    assert result['reviewDiagnosticAudit']['targetStructureReferences']==[]
    assert result['reviewDiagnosticAudit']['errors']==old['reviewDiagnosticAudit']['errors']
    assert result['reviewDiagnosticAudit']['newNumberCount']==old['reviewDiagnosticAudit']['newNumberCount']


def test_meta_count_cannot_hide_equal_scientific_count_elsewhere_in_reason():
    verdict,claim,ev=case('前三个分句说明使用3个数据集。');result=bind(verdict,claim,ev,target_structure=True)
    assert result['reviewDiagnosticAudit']['targetStructureReferences'] and result['reviewDiagnosticAudit']['unboundNewNumberCount']==1


def test_unavailable_target_units_are_not_counted_from_source_or_another_claim():
    verdict,claim,ev=case('前三个分句不成立。');claim['text']='One statement.';ev[0]['quote']=TEXT
    result=bind(verdict,claim,ev,target_structure=True)
    assert not result['reviewDiagnosticAudit']['targetStructureReferences'] and result['reviewDiagnosticAudit']['errors']


def test_paragraph_capacity_is_bound_to_actual_target_newlines():
    assert view('前两段',TEXT)[1]==[]
    assert len(view('前两段','A paragraph.\nAnother paragraph.')[1])==1


@pytest.mark.parametrize('status',['passed','failed'])
def test_scientific_decision_is_preserved_and_legacy_off_is_exact(status):
    verdict,claim,ev=case();verdict['status']=status
    old=bind(verdict,claim,ev);same=bind(verdict,claim,ev,target_structure=False)
    assert old==same and 'reviewTargetStructureContractVersion' not in old['reviewDiagnosticAudit']
    new=bind(verdict,claim,ev,target_structure=True);assert new['status']==status


@pytest.mark.parametrize('mutation',['statement','excerpt','foreign','path'])
def test_navigation_does_not_relax_actual_bound_source_fact_validation(mutation):
    verdict,claim,ev=case('前三个分句不成立。 The coefficient is 0.125.')
    ev[0]['quote']='The coefficient is 0.125.'
    fact={'statement':'The coefficient is 0.125.','evidenceId':'own','path':['quote'],'excerpt':ev[0]['quote']}
    # Use the actual own identity from the standard fixture.
    fact['evidenceId']=ev[0]['evidenceId']
    if mutation=='statement':fact['statement']='Different statement.'
    elif mutation=='excerpt':fact['excerpt']='The coefficient is 0.25.'
    elif mutation=='foreign':fact['evidenceId']='foreign'
    else:fact['path']=['sourceTitle']
    verdict['diagnosticFacts']=[fact]
    assert bind(verdict,claim,ev,target_structure=True)['reviewDiagnosticAudit']['errors']


@pytest.mark.parametrize('value',[None,0,1,'true'])
def test_policy_requires_strict_bool(value):
    with pytest.raises(ValueError):bind(*case(),target_structure=value)


@pytest.mark.parametrize('supported',[True,False])
def test_actual_checker_keeps_request_exact_while_interpreting_only_new_policy(supported):
    _,claim,ev=case();raw={**response(supported),'reason':'前三个分句由材料支持。','diagnosticFacts':[]};calls=[]
    def invoke(**kwargs):calls.append(kwargs);return {'content':json.dumps([raw])}
    old=checker(invoke,review_diagnostic_bindings=True)([claim],ev)[0];old_request=calls.pop()
    new=checker(invoke,review_diagnostic_bindings=True,diagnostic_target_structure=lambda:True)([claim],ev)[0]
    assert calls==[old_request] and old['executionState']=='received_invalid'
    assert new['reviewDiagnosticAudit']['errors']==[] and new['status']==('passed' if supported else 'failed')


def test_new_profile_is_server_owned_immutable_and_never_added_to_old_runs(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object());key='reviewTargetStructureContractVersion'
    try:
        row,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain',key:False},start_async=False)
        assert type(row[key]) is int and row[key]==1 and facade._make_semantic_checker(row['runId'])._diagnostic_target_structure() is True
        old=deepcopy(row);old.pop(key);old.update(runId='old',idempotencyKey='old');repo.create_run(old)
        assert facade._make_semantic_checker('old')._diagnostic_target_structure() is False
        for rid in (row['runId'],'old'):
            with pytest.raises(ValueError,match='Immutable'):repo.update_run(rid,lambda r:{**r,key:2})
    finally:facade.shutdown()


def test_untransmitted_generated_configuration_prose_cannot_authorize_target_navigation():
    from test_deep_research_execution_materialization import analysis_claim
    from services.deep_research.execution_materialization import materialize_execution_claim,verification_claim_view
    claim=materialize_execution_claim(analysis_claim());claim['evidenceRefs']=[]
    assert verification_claim_view(claim)['text']==analysis_claim()['text']
    reason='前三个分句不成立。';verdict={'claimId':claim['claimId'],'status':'failed','reason':reason,'diagnosticFacts':[]}
    result=bind(verdict,claim,[],target_structure=True)
    assert result['reviewDiagnosticAudit']['targetStructureReferences']==[]
    assert result['reviewDiagnosticAudit']['errors']==['new_diagnostic_numbers_not_bound']


def test_source_owner_after_chinese_target_like_phrase_is_never_exempted():
    assert view('前三句原文说明条件',TEXT)[1]==[]


@pytest.mark.parametrize('owner',['E1','E1：','E_1: ','P2：','Q3: ','T4：',
    'ev_'+'a1'*32+'：','evidence: ','arxiv: ','doi: '])
def test_source_alias_before_location_is_not_target_navigation(owner):
    verdict,claim,ev=case(owner+'前三个分句说明结论。')
    old=bind(verdict,claim,ev);new=bind(verdict,claim,ev,target_structure=True)
    assert new['reviewDiagnosticAudit']['targetStructureReferences']==[]
    assert new['reviewDiagnosticAudit']['errors']==old['reviewDiagnosticAudit']['errors']
    assert new['reviewDiagnosticAudit']['newNumberCount']==old['reviewDiagnosticAudit']['newNumberCount']


def test_completed_source_clause_does_not_own_later_target_navigation():
    scanned,refs=view('E1支持该定义，但最后一个分句不成立。',TEXT)
    assert len(refs)==1 and refs[0]['text']=='最后一个分句'
    assert 'E1' in scanned
