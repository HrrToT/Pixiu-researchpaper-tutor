from copy import deepcopy
import pytest
from services.deep_research.structured_output import messages_for_record
from services.deep_research.compaction_editor import SYSTEM


def record(version=1):
    return {'structuredOutputContractVersion':15,'draftSystemContractVersion':1,
        'compactionEditorContractVersion':version,'state':{'outputKind':'direction_survey'}}


def test_editor_role_replaces_research_repair_only_for_new_compaction():
    prompt='只精简三个原点，300字以内。';r=record();before=deepcopy(r)
    new=messages_for_record(r,'synthesize_compact',prompt)
    old=messages_for_record(record(0),'synthesize_compact',prompt)
    assert new==[{'role':'system','content':SYSTEM},{'role':'user','content':prompt}]
    assert 'Fix ALL checks' in old[0]['content'] and 'Fix ALL checks' not in SYSTEM
    assert 'HARD character allowance' in SYSTEM and len(SYSTEM.encode())+128<=1024
    assert r==before


@pytest.mark.parametrize('node',['synthesize','repair_claims','verify','plan','verify_advice','synthesize_audience'])
def test_other_roles_remain_byte_identical(node):
    assert messages_for_record(record(1),node,'prompt')==messages_for_record(record(0),node,'prompt')


@pytest.mark.parametrize('version',[None,True,0,3,'1'])
def test_noninteger_or_unknown_editor_flag_cannot_select_role(version):
    assert messages_for_record(record(version),'synthesize_compact','p')==messages_for_record(record(0),'synthesize_compact','p')


@pytest.mark.parametrize('replacement',[None,True,0,3,'1'])
def test_editor_contract_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'说明方法','deferStart':True,
            'compactionEditorContractVersion':replacement},start_async=False)
        assert run['compactionEditorContractVersion']==2
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'compactionEditorContractVersion':replacement})
    finally:facade.shutdown()


def test_measured_editing_targets_sum_to_headroom_without_mutating_input():
    import json
    from services.deep_research.compaction_editor import budget_guidance
    rows=[{'claimId':str(i),'text':'中'*n,'conditions':{}} for i,n in enumerate((80,140,70))]
    before=deepcopy(rows);prompt=budget_guidance(rows,263)
    value=json.JSONDecoder().raw_decode(prompt.split('服务器实测编辑预算：',1)[1])[0]
    assert value['currentCharacters']==290 and value['draftTarget']==223
    assert sum(p['targetCharacters'] for p in value['points'])==223
    assert value['minimumReductionToTarget']==67
    assert value['points'][1]['targetCharacters']>value['points'][0]['targetCharacters']>=value['points'][2]['targetCharacters']
    assert rows==before


@pytest.mark.parametrize('allowance',[1,2,7,31,263,1000])
def test_budget_allocation_never_invents_capacity(allowance):
    import json
    from services.deep_research.compaction_editor import budget_guidance
    rows=[{'claimId':str(i),'text':'中'*n,'conditions':{}} for i,n in enumerate((3,20,100,1))]
    value=json.JSONDecoder().raw_decode(budget_guidance(rows,allowance).split('服务器实测编辑预算：',1)[1])[0]
    assert sum(p['targetCharacters'] for p in value['points'])==value['draftTarget']<=allowance
    assert all(p['targetCharacters']>=0 for p in value['points'])


def test_actual_compaction_receives_measured_budget_and_keeps_scientific_contract():
    import json
    from unittest.mock import Mock
    from services.deep_research.answer_constraints import compact_answer
    original={'claims':[{'claimId':key,'text':'原有解释。'*40,'kind':kind,'evidenceRefs':[key],
        'conditions':{},'obligationIds':[key+'-goal']} for key,kind in [('method','reported'),('reading','proposal')]]}
    # Neither measurements nor citations are synthesized by budget allocation.
    edited={'claims':[{'claimId':'method','text':'剪枝减少高斯。','conditions':{}},
                      {'claimId':'reading','text':'建议先读方法。','conditions':{}}]}
    invoke=Mock(return_value={'content':json.dumps(edited)})
    result=compact_answer(original,'300字以内',invoke,json.loads,preserve_answers=True,
        measured_edit_budget=True,presentation_version=4)
    assert result and '服务器实测编辑预算' in invoke.call_args.args[0]
    assert [c['evidenceRefs'] for c in result['claims']]==[['method'],['reading']]
    assert [c['kind'] for c in result['claims']]==['reported','proposal']
    legacy=Mock(return_value={'content':json.dumps(edited)})
    compact_answer(original,'300字以内',legacy,json.loads,preserve_answers=True,presentation_version=4)
    assert '服务器实测编辑预算' not in legacy.call_args.args[0]
