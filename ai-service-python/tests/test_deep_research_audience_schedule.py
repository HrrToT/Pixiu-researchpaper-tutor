from copy import deepcopy
import json
import pytest
from services.deep_research.audience_schedule import reader_first
from services.deep_research.graph import make_synthesize_node
from test_deep_research_factual_prompt import node_capture


def run(monkeypatch,flag=1,outcome='applied'):
    _,_,record=node_capture(1)
    record.update(question='给新手解释方法，限100字。',audienceRewriteContractVersion=9,
        audienceFirstContractVersion=flag)
    record['state']['outputKind']='claim_verification'
    events=[];edits=[]
    def update(rid,fn,**kw):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    def reader(report,evidence,question,invoke,parse,**kwargs):
        events.append('reader');edits.append(deepcopy(report))
        if outcome=='unknown':raise OSError('Unknown response; no fallback dispatch')
        result=deepcopy(report)
        if outcome=='applied':result['claims'][0]['text']='从观测中计算深度，再融合为表面。'
        return result
    monkeypatch.setattr('services.deep_research.audience_rewrite.rewrite_for_beginner',reader)
    def invoke(rid,node,prompt,options,**kw):
        events.append(node)
        if node=='synthesize':
            return {'content':json.dumps({'sections':[],'claims':[{'claimId':'c','kind':'reported',
                'text':'很长的机制说明。'*35,'evidenceRefs':['E1'],'obligationIds':['o'],
                'detailLevel':'fulltext','conditions':{}}]})}
        assert node=='synthesize_compact'
        return {'content':json.dumps({'claims':[{'claimId':'c','text':'从观测中计算深度，再融合为表面。','conditions':{}}]})}
    if outcome=='unknown':
        with pytest.raises(OSError):make_synthesize_node(invoke,update)({'run_id':'r'})
    else:assert 'report_version_id' in make_synthesize_node(invoke,update)({'run_id':'r'})
    return events,record,edits


def test_short_valid_reader_edit_precedes_and_eliminates_unnecessary_compaction(monkeypatch):
    events,r,edits=run(monkeypatch)
    assert events==['synthesize','reader'] and len(edits)==1
    assert r['state']['reportBody']['claims'][0]['text']=='从观测中计算深度，再融合为表面。'
    assert not r['state'].get('verifiedReport')


def test_rejected_reader_edit_uses_one_existing_compaction_without_second_reader_call(monkeypatch):
    events,r,edits=run(monkeypatch,outcome='rejected')
    assert events==['synthesize','reader','synthesize_compact'] and len(edits)==1
    before=edits[0]['claims'][0];after=r['state']['reportBody']['claims'][0]
    assert all(before.get(k)==after.get(k) for k in ('kind','evidenceRefs','obligationIds','detailLevel'))


def test_unknown_reader_transport_propagates_without_compaction_fallback(monkeypatch):
    events,_,_=run(monkeypatch,outcome='unknown')
    assert events==['synthesize','reader']


@pytest.mark.parametrize('flag',[None,True,False,0,2,1.0,'1'])
def test_legacy_or_invalid_flag_keeps_original_order(monkeypatch,flag):
    events,_,_=run(monkeypatch,flag=flag)
    assert events==['synthesize','synthesize_compact','reader']


@pytest.mark.parametrize('question', ['详细解释方法，限100字。','给新手解释方法。',
    '给新手解释方法，限800字。','不要面向新手，限100字。'])
def test_no_short_explicit_reader_request_keeps_original_admission(question):
    report={'claims':[{'claimId':'c','kind':'reported','text':'说明。','evidenceRefs':['e']}]}
    r={'question':question,'audienceRewriteContractVersion':9,'audienceFirstContractVersion':1}
    assert not reader_first(r,report,'claim_verification')
    assert not reader_first({**r,'question':'给新手解释方法，限100字。'},report,'experiment_design')


def test_server_owns_immutable_schedule_and_old_runs_cannot_acquire_it(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'给新手解释方法，限100字。','deferStart':True,
            'audienceFirstContractVersion':False},start_async=False)
        assert type(r['audienceFirstContractVersion']) is int and r['audienceFirstContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(r['runId'],lambda r:{**r,'audienceFirstContractVersion':False})
        old=deepcopy(r);old.pop('audienceFirstContractVersion');old.update(runId='legacy',idempotencyKey='old');repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('legacy',lambda r:{**r,'audienceFirstContractVersion':1})
    finally:facade.shutdown()
