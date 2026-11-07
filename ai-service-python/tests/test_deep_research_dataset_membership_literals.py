from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.dataset_membership import table_spans
from services.deep_research.extraction import make_batched_extract_node
from services.deep_research.synthesis_evidence import order_premises
from services.deep_research.verification import make_evidence,verify_claims
from test_deep_research_synthesis_premises import evidence,claim

TABLE='''Table row 17: Dataset A [cols=3, rows=1] | Dataset B [cols=3, rows=1]
Table row 18: Scene | FPS | Count | Scene | FPS | Count
Table row 19: FirstScene | 24 | 300 | OtherScene | 48 | 185'''
BODY=TABLE+'''
Our implementation uses a shared setting.
We evaluate the scene measurements.
Our method has a supplementary experiment.'''


def test_complete_adjacent_header_member_rows_stay_literal_without_inferred_mapping():
    spans=table_spans(BODY,['核对拟议数据选择的现有场景或样本依据。'])
    assert spans==[TABLE]
    assert table_spans(BODY,['解释时间表示'])==[]
    for text in [TABLE.replace('Table row 18:', 'Skipped header:'),
                 TABLE.replace('FirstScene','...'),TABLE.replace('FirstScene','Ours')]:
        assert table_spans(text,['核对数据集成员'])==[]


@pytest.mark.parametrize('version',[7,8])
def test_membership_span_occupies_one_of_three_existing_extraction_slots(version):
    current={'extractionPriorityVersion':version,'adaptiveResearchContractVersion':1,
        'adaptiveExtractionContractVersion':1,'state':{'evidence':[],
        'plan':[{'obligations':[{'obligationId':'o','question':'核对数据集成员','requiredSources':['p']}]}],
        'readResults':[{'sourceId':'s','workId':'p','versionId':'v','contentHash':'h','accessLevel':'fulltext',
            'location':{'tableColumnMappingUnverified':True},'pages':[{'text':BODY,'section':'Results'}]}]}}
    before=deepcopy(current);sent=[]
    def update(_id,change,**kw):
        nonlocal current
        current=change(deepcopy(current));return deepcopy(current)
    def invoke(_id,node,prompt,options):
        sent.append(prompt)
        return {'content':json.dumps([{'sourceId':'s','quote':q,'obligationIds':['o']} for q in BODY.splitlines()[-3:]])}
    make_batched_extract_node(invoke,make_evidence,lambda *_:True,update)({'run_id':'r'})
    rows=current['state']['evidence'];assert len(rows)==3
    literal=[r for r in rows if r.get('extractionKind')=='literal_dataset_member_rows']
    assert bool(literal)==(version==8)
    if literal:
        row=literal[0]
        assert row['quote']==TABLE and row['location']['tableColumnMappingUnverified'] is True
        assert row['verification']=={'literal':'passed','semantic':'unchecked'}
        assert not row.get('tableData')
        check=Mock(return_value=[{'claimId':'c','status':'failed','reason':'Columns do not establish this membership.'}])
        assert not verify_claims([claim('FirstScene belongs to Dataset B.',(row['evidenceId'],),'inference')],rows,check)['accepted']
        check.assert_called_once()
        assert 'literalDatasetMemberRowsAlreadySaved' in sent[0]
    assert current['state']['readResults']==before['state']['readResults']


def test_membership_premise_survives_before_optional_benefits_without_changing_old_allocation():
    rows=[evidence('noise'+str(i),'Our scene has a useful result.') for i in range(21)]
    rows.append({**evidence('member',TABLE),'extractionKind':'literal_dataset_member_rows'})
    plan=[{'obligations':[{'obligationId':'data','question':'核对数据选择','requiredSources':['p'],
        'completionCriteria':[{'criterionId':'members','requirement':'核对拟议数据选择的现有场景或样本依据。',
            'responseType':'explanation'}]}]}]
    before=deepcopy((rows,plan))
    legacy,_=order_premises(rows,plan)
    new,bundles=order_premises(rows,plan,membership_intents=True)
    assert 'member' not in {r['evidenceId'] for r in legacy}
    assert new[0]['evidenceId']=='member' and bundles[0]['evidenceIds']==['member']
    assert (rows,plan)==before


def test_unread_retrieved_member_table_gets_one_original_read_slot_before_background():
    from services.deep_research.reading_priority import select_read_sources
    from test_deep_research_reading_priority import source
    obligation={'obligationId':'o','question':'选择现有场景的依据','requiredSources':['p'],
        'completionCriteria':[{'requirement':'核对拟议数据选择的现有场景或样本依据。','responseType':'explanation'}]}
    rows=[source('p',1,'Background','Our model learns and updates a representation with useful input signals.',('o',)),
          source('p',56,'Results',TABLE,('o',))]
    before=deepcopy(rows)
    assert select_read_sources(rows,{'o':obligation},1,priority_version=7)==[rows[0]]
    assert select_read_sources(rows,{'o':obligation},1,priority_version=8)==[rows[1]]
    assert rows==before


@pytest.mark.parametrize('access',['abstract','user_note'])
def test_non_fulltext_does_not_gain_program_dataset_members(access):
    from test_deep_research_criterion_sources import extract_record
    current=extract_record(version=8,access=access)
    current['state']['readResults'][0]['pages'][0]['text']=BODY
    current['state']['plan'][0]['obligations'][0]['question']='核对数据集成员'
    def update(_id,change,**kw):
        nonlocal current
        current=change(deepcopy(current));return deepcopy(current)
    make_batched_extract_node(lambda *_:{'content':'[]'},make_evidence,lambda *_:True,update)({'run_id':'r'})
    assert current['state']['evidence']==[]
