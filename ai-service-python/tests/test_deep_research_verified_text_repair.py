from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.repair import _prepare_repair,_parse_repair_response,repair_rejected
from services.deep_research.contracts import DeepResearchError
from test_deep_research_repair_instructions import fixture


def inputs():
    report,verification,ev,opts=fixture()
    opts.update(consolidated_instructions=True,verified_target_ids=['c'])
    return report,verification,ev,opts


def prepare(enabled=True):
    report,verification,ev,opts=inputs()
    return _prepare_repair(report,verification,ev,'Explain the operation.',verified_text_edits=enabled,**opts)


def test_term_insertions_keep_every_original_word_and_citation_with_one_owned_packet():
    from services.deep_research.verified_text_repair import prepare_term_insertions, term_insertions

    one = {'claimId': 'one', 'kind': 'reported', 'text': '球谐系数描述颜色，训练更新球谐系数。',
           'conditions': {'mode': '训练'}, 'evidenceRefs': ['p']}
    two = {'claimId': 'two', 'kind': 'reported', 'text': '蒸馏训练紧凑模型。',
           'conditions': {}, 'evidenceRefs': ['q']}
    originals = {'one': one, 'two': two}
    rejected = {'one': {'reason': 'answer_incomplete', 'beginnerTerms': ['球谐系数']},
                'two': {'reason': 'answer_incomplete', 'beginnerTerms': ['蒸馏']}}
    evidence = [{'evidenceId': eid, 'accessLevel': 'fulltext', 'verification': {'literal': 'passed'}, 'quote': text}
                for eid, text in [('p', 'Own representation.'), ('q', 'Own method.'), ('x', 'Uncited other source.')]]
    scopes = term_insertions(originals, rejected, list(originals), [])
    prepared = prepare_term_insertions(originals, scopes, evidence, 4000)
    assert 'Own representation.' in prepared['prompt'] and 'Own method.' in prepared['prompt']
    assert 'Uncited other source.' not in prepared['prompt']
    rows = [{'claimId': 'one', 'definitions': [{'term': '球谐系数', 'gloss': '描述颜色随观察方向变化的参数'}]},
            {'claimId': 'two', 'definitions': [{'term': '蒸馏', 'gloss': '让小模型模仿大模型的输出'}]}]
    first, second = _parse_repair_response(prepared, {'content': json.dumps(rows)}, json.loads, strict_response=True)
    assert first == {**one, 'text': '球谐系数（描述颜色随观察方向变化的参数）描述颜色，训练更新球谐系数。'}
    assert second == {**two, 'text': '蒸馏（让小模型模仿大模型的输出）训练紧凑模型。'}
    rows[0]['definitions'][0]['gloss'] = '会提升 25 FPS'
    with pytest.raises(DeepResearchError, match='额外内容'):
        _parse_repair_response(prepared, {'content': json.dumps(rows)}, json.loads, strict_response=True)
    assert not term_insertions(originals, rejected, ['one'], [])


def test_coverage_only_text_schema_keeps_all_original_sources_conditions_and_goal_ownership():
    old=prepare(False);new=prepare()
    assert new['verifiedTextRepairContractVersion']==1 and 'verifiedTextRepairContractVersion' not in old
    assert new['originals']==old['originals'] and new['aliases']==old['aliases']
    before=json.JSONDecoder().raw_decode(old['prompt'].split('Exact repair inputs (goals and metadata, not paper facts):\n',1)[1])[0]
    after=json.JSONDecoder().raw_decode(new['prompt'].split('Frozen edit inputs (goals, not paper facts):\n',1)[1])[0]
    assert after['sourceRegistry']==before['sourceRegistry']
    assert new['allowed']=={cid:original['evidenceRefs'] for cid,original in new['originals'].items()}
    assert 'complete revised Chinese text' in new['prompt'] and len(new['prompt'].encode())<len(old['prompt'].encode())
    for e in inputs()[2]:
        if e['evidenceId'] in new['allowed']['c']:assert e['quote'] in new['prompt']


def test_materialization_can_only_change_text_and_every_candidate_is_reverified():
    prepared=prepare();old=deepcopy(prepared['originals']['c'])
    edited=_parse_repair_response(prepared,{'content':json.dumps([{'claimId':'c','text':'新的有据过程解释。'}])},json.loads,strict_response=True)
    assert len(edited)==1 and edited[0]['text']=='新的有据过程解释。'
    assert {k:v for k,v in edited[0].items() if k!='text'}=={k:v for k,v in old.items() if k not in ('text','verification','reviewDiagnosticAudit')}
    assert prepared['originals']['c']==old
    from services.deep_research.verification import verify_claims
    reject=Mock(return_value=[{'claimId':'c','status':'failed','reason':'unsupported edited content'}])
    assert not verify_claims(edited,inputs()[2],reject)['accepted']


@pytest.mark.parametrize(('locator', 'removed'), [
    ('（P1，第13页）', True),
    ('（P1，第13、99页）', False),
    ('（P2，第13页）', False),
    ('（P1，第13页，开销为20 GB）', False),
    ('令Z=（P1，第13页）', False),
    ('`（P1，第13页）`', False),
])
def test_coverage_edit_keeps_only_the_frozen_evidence_and_removes_redundant_page_labels(locator, removed):
    report, verification, evidence, opts = inputs()
    for row in evidence:
        row.update(location={'page': 13, 'pageResolution': 'exact'}, accessLevel='fulltext',
                   verification={'literal': 'passed', 'semantic': 'unchecked'})
    current = _prepare_repair(report, verification, evidence, 'Explain the operation.',
                              verified_text_edits=True, citation_presentation_version=6, **opts)
    legacy = _prepare_repair(report, verification, evidence, 'Explain the operation.',
                             verified_text_edits=True, citation_presentation_version=5, **opts)
    prose = '把原始观测转换成可比较的特征。'
    raw = {'content': json.dumps([{'claimId': 'c', 'text': prose + locator}])}
    audit = []
    [edited] = _parse_repair_response(current, raw, json.loads, presentation_audit=audit)
    [old] = _parse_repair_response(legacy, raw, json.loads)
    assert old['text'] == prose + locator
    assert edited == {**old, 'text': prose if removed else prose + locator}
    assert bool(audit) is removed
    assert edited['evidenceRefs'] == report['claims'][0]['evidenceRefs']
    assert not edited.get('verification')


def test_editing_a_verified_number_still_fails_original_numeric_evidence_gate():
    from services.deep_research.verification import make_evidence,verify_claims
    from services.deep_research.verified_text_repair import materialize
    quote='Method A reports accuracy 95%.'
    ev=make_evidence({'workId':'paper','versionId':'paper-v1','contentHash':'hash','accessLevel':'fulltext'},quote,quote,location={'page':1},obligation_ids=['o'])
    original={'claimId':'c','kind':'reported','text':quote,'conditions':{},'obligationIds':['o'],'evidenceRefs':[ev['evidenceId']]}
    edit=materialize([{'claimId':'c','text':'Method A reports accuracy 99%.'}],{'c':original})
    assert not verify_claims(edit,[ev],Mock(return_value=[{'claimId':'c','status':'passed'}]))['accepted']


@pytest.mark.parametrize('bad',['id','kind','source','conditions','body','duplicate','unchanged'])
def test_foreign_metadata_and_noop_edits_never_enter_verification(bad):
    prepared=prepare();raw={'claimId':'c','text':'新的解释。'}
    if bad=='id':raw['claimId']='foreign'
    elif bad=='kind':raw['kind']='reported'
    elif bad=='source':raw['evidenceRefs']=['foreign']
    elif bad=='conditions':raw['conditions']={}
    elif bad=='body':raw['body']={'prose':{'text':'replacement','conditions':{}}}
    elif bad=='unchanged':raw['text']=prepared['originals']['c']['text']
    rows=[raw,raw] if bad=='duplicate' else [raw]
    with pytest.raises(DeepResearchError):_parse_repair_response(prepared,{'content':json.dumps(rows)},json.loads,strict_response=True)


@pytest.mark.parametrize('bad',['unverified','fact_failure','additional_failure','scope','table','execution'])
def test_factual_repairs_and_structured_content_keep_the_existing_full_redraft_path(bad):
    report,verification,ev,opts=inputs()
    if bad=='unverified':opts['verified_target_ids']=[]
    elif bad=='fact_failure':verification['rejected'][0]['reason']='semantic_unresolved'
    elif bad=='additional_failure':verification['rejected'][0]['additionalChecks']=[{'reason':'semantic_unresolved'}]
    elif bad=='scope':report['claims'][0]['scopeExpression']={'observedSettings':[],'notEstablished':['not proven']}
    elif bad=='table':report['claims'][0]['tableBindings']=[{'evidenceId':ev[0]['evidenceId']}]
    else:
        report['claims'][0]['executionSpec']={'procedure':'fixture'}
        for flag in (False,True):
            with pytest.raises(ValueError):_prepare_repair(report,verification,ev,'Explain the operation.',verified_text_edits=flag,**opts)
        return
    a=_prepare_repair(report,verification,ev,'Explain the operation.',verified_text_edits=False,**opts)
    b=_prepare_repair(report,verification,ev,'Explain the operation.',verified_text_edits=True,**opts)
    assert a==b


def test_settled_batch_is_reused_and_cannot_switch_edit_policy_or_resend():
    report,verification,ev,opts=inputs();states=[];send=Mock(return_value={'content':json.dumps([{'claimId':'c','text':'新的有据解释。'}])})
    args=(report,verification,ev,'Explain the operation.',send,json.loads)
    result=repair_rejected(*args,verified_text_edits=True,checkpoint=states.append,**opts)
    assert result and states[-1]['verifiedTextEditAudit']['0']['requiresFreshVerification']
    assert repair_rejected(*args,verified_text_edits=True,batch_state=states[-1],**opts)==result
    assert send.call_count==1
    with pytest.raises(DeepResearchError):repair_rejected(*args,batch_state=states[-1],**opts)
    assert send.call_count==1


def test_noop_is_saved_as_unusable_response_and_does_not_trigger_another_request():
    report,verification,ev,opts=inputs();states=[]
    send=Mock(return_value={'content':json.dumps([{'claimId':'c','text':report['claims'][0]['text']}])})
    args=(report,verification,ev,'Explain the operation.',send,json.loads)
    assert repair_rejected(*args,verified_text_edits=True,checkpoint=states.append,strict_response=True,**opts)==[]
    assert states[-1]['responseError']['responseState']=='received_invalid'
    assert repair_rejected(*args,verified_text_edits=True,batch_state=states[-1],strict_response=True,**opts)==[]
    assert send.call_count==1


@pytest.mark.parametrize('value',[None,True,False,0,'1',1,3])
def test_server_owns_immutable_edit_policy(tmp_path,value):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        created,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'核查','verifiedTextRepairContractVersion':value},start_async=False)
        run=repo.require_run(created['runId']);assert type(run['verifiedTextRepairContractVersion']) is int and run['verifiedTextRepairContractVersion']==2
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(run['runId'],lambda r:{**r,'verifiedTextRepairContractVersion':value})
    finally:facade.shutdown()
