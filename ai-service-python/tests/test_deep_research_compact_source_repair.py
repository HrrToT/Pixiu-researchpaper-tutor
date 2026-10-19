from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.contracts import DeepResearchError, BudgetExhaustedError
from services.deep_research.factual_repair import compact_rows, enabled,protected_seconds
from services.deep_research.repair import _prepare_repair, repair_rejected, _parse_repair_response
from services.deep_research.repair_budget import repair_batch_output_limit, repair_prompt_byte_limit
from services.deep_research.verification import verify_claims
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from test_deep_research_factual_redraft import inputs


def prepare(new=True, **extra):
    c,e,checks,requirements=inputs()
    return _prepare_repair({'claims':[c]},checks,[e],'解释预测的变化，200字以内',
        fact_redraft=True,source_aware_redraft=True,concise_factual=True,factual_scope=3,
        requirement_context=requirements,compact_source_repair=new,**extra)


def test_compact_prompt_retains_exact_originals_requirements_checks_and_source_permissions():
    c,e,checks,requirements=inputs();prepared=prepare()
    prompt=prepared['prompt']
    assert prompt.startswith('Rebuild ONLY these rejected factual answer targets')
    assert c['text'] not in prompt and c['conditions']['scope'] not in prompt
    assert e['quote'] in prompt and checks['rejected'][0]['detail'] in prompt
    assert requirements[0]['completionCriteria'][0]['requirement'] in prompt
    assert 'FORMER local E IDs' in prompt and 'independent' in prompt.lower()
    assert prepared['originals']=={'c':c} and prepared['allowed']=={'c':c['evidenceRefs']}
    assert len(prompt.encode())<len(prepare(False)['prompt'].encode())
    assert 'draftingBasis' in prompt and 'zero-based' not in prompt  # No table packet here.


def test_only_identical_supplied_metadata_is_deduplicated_and_quotes_context_hashes_remain():
    identity={'scheme':'arxiv','revision':'v1'}
    rows=[{'evidenceId':'E1','quote':'Exact statement.','sourceContext':'Section: Method. Full original context.',
        'sourceRef':'P1','contentHash':'passage-hash','publicationIdentity':identity,'accessLevel':'fulltext',
        'location':{'section':'Method','page':3,'tableColumnMappingUnverified':True}},
        {'evidenceId':'E2','sourceRef':'P2','quote':'Another statement.','sourceContext':'Original context.',
         'publicationIdentity':identity,'accessLevel':'abstract','location':{'section':'Elsewhere'}}]
    before=deepcopy(rows)
    wire=compact_rows(rows,{'sources':{'P1':{'publicationIdentity':identity,'accessLevel':'fulltext'},
                                    'P2':{'publicationIdentity':{'revision':'v2'},'accessLevel':'fulltext'}}})
    assert rows==before and wire[0]['quote']==rows[0]['quote'] and wire[0]['sourceContext']==rows[0]['sourceContext']
    assert wire[0]['contentHash']=='passage-hash' and wire[0]['location']=={'page':3,'tableColumnMappingUnverified':True}
    assert 'publicationIdentity' not in wire[0] and 'accessLevel' not in wire[0]
    assert wire[1]==rows[1]  # Mismatched identity/access or absent section must remain explicit.


def test_preparation_and_parsing_do_not_approve_or_reclassify_unsupported_facts():
    c,e,_,_=inputs();prepared=prepare()
    for kind,refs in [('inference',['E1']),('reported',['UNSUPPLIED'])]:
        response={'content':json.dumps([{'claimId':'c','kind':kind,'text':'Unsupported claim.',
                                       'evidenceRefs':refs,'conditions':{}}])}
        assert not _parse_repair_response(prepared,response,json.loads)
    response={'content':json.dumps([{'claimId':'c','kind':'reported','text':'原文说明的变化。',
                                   'evidenceRefs':['E1'],'conditions':{}}])}
    revisions=_parse_repair_response(prepared,response,json.loads)
    assert revisions and not verify_claims(revisions,[e])['accepted']
    semantic=Mock(return_value=[{'claimId':'c','status':'failed','reason':'Unsupported interpretation'}])
    assert not verify_claims(revisions,[e],semantic)['accepted']
    with pytest.raises(BudgetExhaustedError):prepare(max_prompt_bytes=1)


def test_pending_request_cannot_be_resumed_under_a_different_generation_contract():
    c,e,checks,requirements=inputs();saved=[]
    class Unknown(Exception):pass
    def invoke(_):raise Unknown('No known outcome')
    kwargs=dict(fact_redraft=True,source_aware_redraft=True,concise_factual=True,
                factual_scope=3,requirement_context=requirements)
    with pytest.raises(Unknown):
        repair_rejected({'claims':[c]},checks,[e],'解释',invoke,json.loads,
                        compact_source_repair=True,checkpoint=saved.append,**kwargs)
    assert saved[-1]['pending']['request']['prepared']['prompt'].startswith('Rebuild ONLY')
    send=Mock()
    with pytest.raises(DeepResearchError,match='原始输入'):
        repair_rejected({'claims':[c]},checks,[e],'解释',send,json.loads,
                        compact_source_repair=False,batch_state=saved[-1],**kwargs)
    send.assert_not_called()


def test_real_graph_uses_the_same_output_envelope_for_preflight_and_dispatch(tmp_path,monkeypatch):
    from test_deep_research_end_to_end import FixtureModel,make_facade,create
    import services.deep_research.repair_budget as budget_module
    observed=[];original=budget_module.repair_prompt_byte_limit
    def capture(budget,output_tokens=8192):
        observed.append(output_tokens);return original(budget,output_tokens)
    monkeypatch.setattr(budget_module,'repair_prompt_byte_limit',capture)
    repo,facade,_=make_facade(tmp_path,FixtureModel())
    try:
        record=create(facade);repo.begin_execution(record['runId']);facade._execute_graph(record['runId'])
        assert repo.require_run(record['runId'])['status']=='completed'
        assert observed and set(observed)=={4096}
        assert '99%' not in facade.get(record['runId'])['report']['body']
    finally:facade.shutdown()


def test_output_sizing_uses_existing_reservation_not_additional_budget():
    budget={'maxTokens':100000,'reserveTokens':50000,'tokens':73480,'normalTokens':30521}
    before=deepcopy(budget);output=repair_batch_output_limit(2)
    assert output==4096 and repair_prompt_byte_limit(budget,output)==14359
    assert 14138+output+1024<=50000-budget['normalTokens']
    assert budget==before and repair_prompt_byte_limit(budget)==10263


def test_short_factual_time_floor_preserves_old_and_complex_paths_and_absolute_budget():
    targets=[{'claimId':'c'+str(i),'kind':'reported','text':'结论。'} for i in range(2)]
    record={'question':'比较两篇，450字以内','factualRepairContractVersion':2,
            'budget':{'maxWallClockSeconds':360}}
    before=deepcopy(record)
    assert protected_seconds(record,targets)==60
    assert protected_seconds({**record,'factualRepairContractVersion':1},targets)==90
    assert protected_seconds({**record,'factualRepairContractVersion':True},targets)==90
    assert protected_seconds({**record,'question':'完整研究'},targets)==90
    assert protected_seconds(record,[{**c,'kind':'proposal','designRole':'groups'} for c in targets])==90
    assert protected_seconds({**record,'budget':{'maxWallClockSeconds':120}},targets)==30
    assert record==before


@pytest.mark.parametrize('replacement',[None,True,False,0,'1',3])
def test_new_contract_is_strict_server_owned_and_immutable(tmp_path,replacement):
    repo=DeepResearchRepository(str(tmp_path/'r.sqlite3'));repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        record,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'解释','deferStart':True,
                               'factualRepairContractVersion':replacement},start_async=False)
        assert record['factualRepairContractVersion']==2 and enabled(record)
        assert not enabled({'factualRepairContractVersion':replacement})
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(record['runId'],lambda r:{**r,'factualRepairContractVersion':replacement})
    finally:facade.shutdown()
