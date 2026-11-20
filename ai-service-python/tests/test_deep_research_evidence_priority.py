from copy import deepcopy
import json

import pytest

from services.deep_research.evidence_priority import prioritize_existing_evidence,priority_enabled
from services.deep_research.repair_scope import repair_evidence_scope
from services.deep_research.repair import repair_rejected
from services.deep_research.contracts import DeepResearchError
from services.deep_research.request_context import ResearchQuestion
from services.deep_research.verification import make_evidence,verify_claims


def inputs():
    evidence=[]
    for work in ('a','b'):
        for i in range(12):
            quote=f'Reported benchmark result number {i}.'
            evidence.append(make_evidence({'workId':work,'versionId':'v1','contentHash':work+str(i),'accessLevel':'fulltext'},
                quote,quote,location={'page':i+1},obligation_ids=['o']))
        quote='We report our evaluation using the same GPU platform, dataset resolution and original code configuration.'
        evidence.append(make_evidence({'workId':work,'versionId':'v1','contentHash':work+'-setup','accessLevel':'fulltext'},
            quote,quote,location={'page':20},obligation_ids=['o']))
    refs=[evidence[0]['evidenceId'],evidence[13]['evidenceId']]
    c={'claimId':'c','kind':'inference','text':'Measurements differ.','evidenceRefs':refs,'conditions':{},'obligationIds':['o']}
    return c,evidence


def test_setting_evidence_is_prioritized_inside_same_anchor_and_candidate_cap():
    c,e=inputs();before=deepcopy((c,e));setups={x['evidenceId'] for x in e if 'GPU platform' in x['quote']}
    old=repair_evidence_scope([c],e)['c']
    new=repair_evidence_scope([c],e,question='为什么不同论文的FPS不能直接相除？')['c']
    assert not setups.intersection(old) and setups<=set(new)
    assert old[:2]==new[:2]==c['evidenceRefs'] and len(old)==len(new)==14
    assert (c,e)==before and len({x['evidenceId'] for x in e if x['evidenceId'] in new})==len(new)


def test_priority_never_expands_foreign_version_or_untrusted_candidate_permission():
    c,e=inputs();foreign=deepcopy(e[-1]);foreign['evidenceId']='foreign';foreign['sourceVersionId']='v2'
    untrusted=deepcopy(e[-1]);untrusted['evidenceId']='untrusted';untrusted['verification']={'literal':'unchecked'}
    wrong_work=deepcopy(e[-1]);wrong_work['evidenceId']='wrong-work';wrong_work['sourceWorkId']='outside'
    added=[foreign,untrusted,wrong_work]
    chosen=repair_evidence_scope([c],[*added,*e],question='检查公平比较的实验设置')['c']
    assert len(chosen)==14 and not {x['evidenceId'] for x in added}.intersection(chosen)
    empty=repair_evidence_scope([{**c,'obligationIds':[]}],e,question='实验设置')['c']
    assert empty==c['evidenceRefs']


def test_ordinary_question_and_newest_human_override_keep_old_order_exactly():
    c,e=inputs();q='解释模型预测什么变化'
    assert prioritize_existing_evidence(e,q)==e
    layered=ResearchQuestion(q+' Previous request: compare experimental conditions',[q,'核查实验设置'])
    assert prioritize_existing_evidence(e,layered)==e
    assert repair_evidence_scope([c],e,question=q)==repair_evidence_scope([c],e)


def test_gpu_method_word_alone_does_not_displace_direct_evaluation_settings():
    rows=[{'quote':'A fast GPU sorting algorithm renders results.'},
          {'quote':'We report all experiments on the same GPU using a fixed configuration.'},
          {'quote':'Table row 4: Ours dataset FPS results'}]
    ordered=prioritize_existing_evidence(rows,'Compare experimental conditions')
    assert ordered[0] is rows[1] and len(ordered)==len(rows)


def test_selected_source_is_not_an_automatic_factual_pass():
    c,e=inputs();chosen=repair_evidence_scope([c],e,question='核查实验设置')['c']
    assert len(chosen)==14
    assert not verify_claims([{**c,'evidenceRefs':chosen}],e)['accepted']


def test_pending_request_cannot_change_candidate_priority_after_unknown_transport():
    c,e=inputs();states=[]
    def unknown(*_): raise OSError('Unknown transport')
    report={'claims':[c]};checks={'accepted':[],'rejected':[{'claimId':'c','reason':'semantic_unresolved'}]}
    with pytest.raises(OSError):
        repair_rejected(report,checks,e,'检查实验设置',unknown,json.loads,checkpoint=states.append,question_priority=True)
    with pytest.raises(DeepResearchError):
        repair_rejected(report,checks,e,'检查实验设置',lambda *_:pytest.fail('No retarget'),json.loads,
                         batch_state=states[-1],question_priority=False)


@pytest.mark.parametrize('value',[None,True,False,0,'1',2])
def test_priority_server_version_is_strict(value):
    assert not priority_enabled({'repairEvidencePriorityVersion':value})
    assert priority_enabled({'repairEvidencePriorityVersion':1})


@pytest.mark.parametrize('value',[None,True,0,2])
def test_priority_contract_is_immutable(tmp_path,value):
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(str(tmp_path/'runs.sqlite3'));repo.initialize();repo.create_run({'runId':'r','repairEvidencePriorityVersion':1})
    with pytest.raises(ValueError,match='Immutable run field'):
        repo.update_run('r',lambda r:{**r,'repairEvidencePriorityVersion':value})


def test_client_cannot_disable_server_priority(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(str(tmp_path/'runs.sqlite3'));repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        p,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'检查实验设置','materials':[],
                          'repairEvidencePriorityVersion':0},start_async=False)
        assert repo.require_run(p['runId'])['repairEvidencePriorityVersion']==1
    finally: facade.shutdown()
