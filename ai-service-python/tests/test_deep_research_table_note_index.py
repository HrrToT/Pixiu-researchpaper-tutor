from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.table_note_index import build,GUIDANCE


def packet():
    table={'evidenceId':'E1','quote':'Table row 1: Base * | .8\nTable row 2: Ours | .7','tableData':{'groups':[['Dataset',['score']]],'rows':[[1,'Base *',['.8']],[2,'Ours',['.7']]]}}
    note={'evidenceId':'E2','quote':'Results marked by ∗ use re-trained baselines.'}
    return [table,note],{'E1':('work','v1'),'E2':('work','v1')},{'E1','E2'}


def test_literal_marker_candidate_is_not_a_meaning_or_citation_and_inputs_remain_unchanged():
    rows,owners,lit=packet();before=deepcopy((rows,owners))
    out=build(rows,owners,literal_ids=lit)
    assert out['tables']==[{'tableEvidenceId':'E1','markedRows':[{'rowNumber':1,'method':'Base *','marker':'*'}],'candidateNoteEvidenceIds':['E2'],'applicabilityUnverified':True,'ambiguous':False}]
    assert 're-trained' not in json.dumps(out) and (rows,owners)==before
    out['tables'][0]['candidateNoteEvidenceIds'].clear();assert rows==before[0]


@pytest.mark.parametrize('mode',['different_work','different_version','missing_identity','not_literal','duplicate','missing_marker','no_definition_cue','not_visible_table','hidden_context'])
def test_nonvisible_unverified_or_foreign_notes_cannot_supply_navigation(mode):
    rows,owners,lit=packet()
    if mode=='different_work':owners['E2']=('other','v1')
    elif mode=='different_version':owners['E2']=('work','v2')
    elif mode=='missing_identity':owners['E2']=('work',None)
    elif mode=='not_literal':lit.remove('E2')
    elif mode=='duplicate':rows.append(deepcopy(rows[1]))
    elif mode=='missing_marker':rows[1]['quote']='Results are marked in the table.'
    elif mode=='no_definition_cue':rows[1]['quote']='Multiply x ∗ y to obtain a feature.'
    elif mode=='not_visible_table':rows[0]['quote']='Table row 2: Ours | .7'
    elif mode=='hidden_context':rows[1].update(quote='Unrelated visible sentence.',sourceContext={'after':rows[1]['quote']},contextOmitted=True)
    assert build(rows,owners,literal_ids=lit)['tables']==[]


def test_ambiguity_is_retained_and_a_note_may_explicitly_mean_something_other_than_retraining():
    rows,owners,lit=packet();rows.append({'evidenceId':'E3','quote':'∗ denotes frozen weights, not retraining.'});owners['E3']=('work','v1');lit.add('E3')
    t=build(rows,owners,literal_ids=lit)['tables'][0]
    assert t['candidateNoteEvidenceIds']==['E2','E3'] and t['ambiguous'] is True
    assert 'frozen' not in json.dumps(t)


def test_both_note_and_table_must_already_be_permitted_for_the_same_target():
    rows,owners,lit=packet();permissions={'a':['E1'],'b':['E2']};before=deepcopy(permissions)
    assert build(rows,owners,literal_ids=lit,permissions=permissions)=={'tables':[],'byClaim':{'a':[],'b':[]}}
    permissions['a'].append('E2');out=build(rows,owners,literal_ids=lit,permissions=permissions)
    assert out['byClaim']['a'][0]['candidateNoteEvidenceIds']==['E2'] and out['byClaim']['b']==[]
    assert before=={'a':['E1'],'b':['E2']}


def test_visible_context_can_supply_a_candidate_but_omitted_table_data_cannot():
    rows,owners,lit=packet();rows[1].update(quote='Nearby paragraph.',sourceContext={'after':'∗ indicates a reproduced baseline.'})
    assert build(rows,owners,literal_ids=lit)['tables']
    rows[0]['tableDataOmitted']=True
    assert build(rows,owners,literal_ids=lit)['tables']==[]


def evidence_packet():
    rows,owners,lit=packet()
    for row in rows:row.update(sourceWorkId='work',sourceVersionId='v1',accessLevel='fulltext',obligationIds=['o'],verification={'literal':'passed'})
    c={'claimId':'c','kind':'inference','text':'Base*是重训比较。','conditions':{},'evidenceRefs':['E1'],'obligationIds':['o'],'detailLevel':'fulltext'}
    return c,rows


def test_repair_index_does_not_change_permissions_and_cache_identity_is_new():
    from services.deep_research.repair import _prepare_repair,repair_rejected
    from services.deep_research.contracts import DeepResearchError
    c,e=evidence_packet();report={'claims':[c]};checks={'accepted':[],'rejected':[{'claimId':'c','reason':'semantic_unresolved'}]}
    legacy=_prepare_repair(report,checks,e,'核查',table_identity_context=True)
    current=_prepare_repair(report,checks,e,'核查',table_identity_context=2)
    assert current['allowed']==legacy['allowed'] and current['originals']==legacy['originals']
    assert GUIDANCE in current['prompt'] and GUIDANCE not in legacy['prompt']
    index=json.loads(current['prompt'].rsplit('Table-note candidates (unverified navigation):\n',1)[1])
    assert index['byClaim']['c']
    refs=current['allowed']['c'];assert len(refs)==2
    # No references are attached by the index. This mocked incomplete reply stays unchanged.
    row={**c,'text':'重写的有界比较。'};invoke=Mock(return_value={'content':json.dumps([row])});states=[]
    out=repair_rejected(report,checks,e,'核查',invoke,json.loads,table_identity_context=2,checkpoint=states.append)
    assert out[0]['evidenceRefs']==['E1']
    saved=deepcopy(states[-1]);invoke.reset_mock()
    assert repair_rejected(report,checks,e,'核查',invoke,json.loads,table_identity_context=2,batch_state=saved)==out
    invoke.assert_not_called()
    with pytest.raises(DeepResearchError):repair_rejected(report,checks,e,'核查',invoke,json.loads,table_identity_context=True,batch_state=saved)
    invoke.assert_not_called()
