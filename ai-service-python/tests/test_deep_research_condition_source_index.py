from copy import deepcopy
import json
import pytest
from services.deep_research.condition_source_index import build,GUIDANCE
from services.deep_research.repair import _prepare_repair


def table(eid='E1',source='P1'):
    return {'evidenceId':eid,'sourceRef':source,'quote':'Table row 8: Base* | 1 | 2\nTable row 10: Ours | 3 | 4',
        'tableData':{'groups':[['Dataset A / mean',['score']],['Dataset B',['score']]],
                     'rows':[[8,'Base*',['1','2']],[10,'Ours',['3','4']],[11,'Not quoted',['5','6']]]}}


def test_navigation_copies_only_visible_literal_tables_and_existing_permissions():
    rows=[table(),table('E2','P2'),{'evidenceId':'E3','quote':'Related method tested Dataset X.'}]
    permissions={'c1':['E1','E3'],'c2':['E2'],'c3':['E3']};before=deepcopy((rows,permissions))
    out=build(rows,permissions,literal_ids={'E1','E2','E3'})
    assert out['tables'][0]=={'evidenceId':'E1','sourceRef':'P1','groups':['Dataset A / mean','Dataset B'],
        'methods':[[8,'Base*'],[10,'Ours']]}
    assert out['allowedTablesByClaim']=={'c1':['E1'],'c2':['E2'],'c3':[]}
    assert out['tables'][1]['sourceRef']=='P2' and (rows,permissions)==before
    out['tables'][0]['groups'][0]='changed'
    assert rows[0]['tableData']['groups'][0][0]=='Dataset A / mean'


@pytest.mark.parametrize('mode',['not_literal','not_permitted','duplicate_id','bad_packet','duplicate_row','blank_group'])
def test_unsafe_or_ambiguous_metadata_cannot_create_a_condition_candidate(mode):
    rows=[table()];permissions={'c':['E1']};literal={'E1'}
    if mode=='not_literal':literal=set()
    elif mode=='not_permitted':permissions={'c':['E2']}
    elif mode=='duplicate_id':rows.append(table())
    elif mode=='bad_packet':rows[0]['tableData']['rows'][0][2]=[]
    elif mode=='duplicate_row':rows[0]['tableData']['rows'].append(rows[0]['tableData']['rows'][0])
    elif mode=='blank_group':rows[0]['tableData']['groups'][0][0]=' '
    assert build(rows,permissions,literal_ids=literal)['tables']==[]


def test_same_group_names_never_merge_different_paper_or_version_sources():
    rows=[table('E1','P-v1'),table('E2','P-v2')]
    out=build(rows,{'c1':['E1'],'c2':['E2']},literal_ids={'E1','E2'})
    assert [t['sourceRef'] for t in out['tables']]==['P-v1','P-v2']
    assert out['allowedTablesByClaim']=={'c1':['E1'],'c2':['E2']}


def test_only_new_repair_profile_gets_navigation_and_fitting_uses_visible_rows():
    t=table();ev={**t,'evidenceId':'e','sourceWorkId':'paper','sourceVersionId':'v1','contentHash':'h',
        'accessLevel':'fulltext','verification':{'literal':'passed'}}
    c={'claimId':'c','kind':'reported','text':'作者报告结果。','evidenceRefs':['e'],'obligationIds':['o']}
    args=({'claims':[c]},{'accepted':[],'rejected':[{'claimId':'c','reason':'answer_incomplete'}]},[ev],'核查条件，200字以内')
    new=_prepare_repair(*args,claim_check=7);old=_prepare_repair(*args,claim_check=6)
    assert GUIDANCE in new['prompt'] and GUIDANCE not in old['prompt']
    index=json.loads(new['prompt'].split('Condition source index (navigation only):\n',1)[1])
    assert index['allowedTablesByClaim']=={'c':['E1']}
    assert new['allowed']==old['allowed'] and new['originals']==old['originals']
    assert json.dumps(ev['quote'],ensure_ascii=False) in new['prompt'] and 'NOT scientific support' in new['prompt']


def test_unverified_mapping_remains_explicitly_unverified_navigation_not_approval():
    row=table();row['location']={'tableColumnMappingUnverified':True}
    out=build([row],{'c':['E1']},literal_ids={'E1'})
    assert out['tables'][0]['columnMappingUnverified'] is True
    assert 'verification' not in out['tables'][0] and 'supported' not in out['tables'][0]
    assert 'UNVERIFIED' in GUIDANCE and 'no geometry or factual approval' in GUIDANCE
