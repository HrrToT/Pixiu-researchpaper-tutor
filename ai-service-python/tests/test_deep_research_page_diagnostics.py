from copy import deepcopy
import json
import subprocess

import pytest
import requests

from services.deep_research.contracts import DeepResearchError
from services.deep_research.page_diagnostics import PageDiagnostics,append,enabled
from services.deep_research.text_quality import guard
from test_deep_research_located_evidence import setup,QUOTE


def test_success_and_failure_observations_do_not_change_pages_retry_or_quotes():
    factory,source,record,local=setup();record['sourceGlyphContractVersion']=1
    factory=guard(factory,record);args=dict(location={'page':1},obligation_ids=['o'])
    response=local.load_pages.return_value
    local.load_pages.side_effect=[requests.Timeout('secret https://private/?token=secret'),response,response]
    with factory.physical_page_batch():
        first=factory(source,QUOTE,QUOTE,**args)
        second=factory(source,QUOTE,QUOTE,**args)
        third=factory(source,QUOTE,QUOTE,**args)
    audit=factory.physical_page_diagnostics()
    assert first['location']['pageResolution']=='unresolved'
    assert second==third and second['location']['page']==2 and second['quote']==QUOTE
    assert audit['quotes']==3 and audit['loads']==2 and audit['cacheHits']==1
    assert audit['failures']=={'file_request_timeout':1}
    assert audit['resolutions']=={'unresolved':1,'exact':2}
    assert audit['loadSeconds']>=0 and audit['repositorySeconds']>=0
    assert 'secret' not in json.dumps(audit) and QUOTE not in json.dumps(audit)
    frozen=deepcopy(audit);audit['loads']=999
    assert factory.physical_page_diagnostics()==frozen
    with factory.physical_page_batch():factory(source,QUOTE,QUOTE,**args)
    assert factory.physical_page_diagnostics()['quotes']==1 and local.load_pages.call_count==3


@pytest.mark.parametrize('error,code',[
    (subprocess.TimeoutExpired('do-not-store-this-command',20),'pdf_parse_timeout'),
    (requests.ConnectionError('do-not-store-this-url'),'file_request_failed'),
    (DeepResearchError('source_parse_failed','private stderr'),'source_parse_failed'),
    (DeepResearchError('source_unavailable','private URL'),'source_unavailable'),
    (DeepResearchError('unexpected_private_code','private'),'source_read_failed')])
def test_failure_codes_are_bounded_and_do_not_store_exception_details(error,code):
    audit=PageDiagnostics();audit.failure(error)
    assert audit.snapshot()['failures']=={code:1}
    assert 'private' not in json.dumps(audit.snapshot()) and 'do-not-store' not in json.dumps(audit.snapshot())


@pytest.mark.parametrize('authorized',[True,False])
def test_diagnostics_and_evidence_share_final_authorization_checkpoint(tmp_path,authorized):
    from services.deep_research.located_evidence import located_evidence_factory
    from services.deep_research.extraction import make_batched_extract_node
    from test_deep_research_source_passages import fixture
    from test_deep_research_adaptive_extraction import activate
    repo,invoke,reads=fixture(tmp_path)
    repo=activate(repo,adaptiveExtractionContractVersion=3,physicalPageDiagnosticsContractVersion=1)
    repo.update_run('r',lambda r:{**r,
        'materials':[{'materialId':s['workId'],'contentHash':'pdf'} for s in reads]})
    class Local:
        calls=0
        def load_pages(self,_):
            self.calls+=1
            raise subprocess.TimeoutExpired('not-saved',20)
    class Scope:
        checks=0
        def validate_materials(self,*args):
            self.checks+=1
            return True if self.checks==1 else authorized
    local=Local();scope=Scope();factory=located_evidence_factory(repo,'r',local)
    node=make_batched_extract_node(invoke,factory,scope,repo.update_run)
    before=deepcopy(repo.require_run('r')['state'])
    if authorized:
        node({'run_id':'r'})
        state=repo.require_run('r')['state'];batch=state['physicalPageDiagnostics']['batches'][0]
        assert batch['loads']==local.calls==batch['quotes']
        assert batch['failures']=={'pdf_parse_timeout':local.calls}
        assert batch['physicalBatchAvailable'] is True and batch['extractionSeconds']>=0
        assert batch['resolutions']=={'unresolved':local.calls}
        assert all(e['verification']['literal']=='passed' and 'page' not in e['location'] for e in state['evidence'])
        before=deepcopy(state);node({'run_id':'r'})
        assert repo.require_run('r')['state']==before
    else:
        with pytest.raises(DeepResearchError,match='未保存'):node({'run_id':'r'})
        assert repo.require_run('r')['state']==before
    invoke.assert_not_called()


def test_history_is_bounded_and_flag_is_strict():
    history=None
    for n in range(30):history=append(history,{'quotes':n})
    assert len(history['batches'])==16 and history['batches'][0]['quotes']==14
    assert enabled({'physicalPageDiagnosticsContractVersion':1})
    assert not enabled({}) and not enabled({'physicalPageDiagnosticsContractVersion':True})


def test_new_server_run_freezes_diagnostic_policy(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **kwargs:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'阅读论文'},start_async=False)
        assert enabled(repo.require_run(run['runId']))
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'physicalPageDiagnosticsContractVersion':True})
    finally:facade.shutdown()


def test_missing_factory_batch_is_observed_without_changing_plain_evidence(tmp_path):
    from test_deep_research_source_passages import fixture,node
    from test_deep_research_adaptive_extraction import activate
    repo,invoke,_=fixture(tmp_path)
    repo=activate(repo,adaptiveExtractionContractVersion=3,physicalPageDiagnosticsContractVersion=1)
    node(repo,invoke)({'run_id':'r'})
    state=repo.require_run('r')['state'];batch=state['physicalPageDiagnostics']['batches'][0]
    assert batch['physicalBatchAvailable'] is False and batch['quotes']==len(state['evidence'])
    invoke.assert_not_called()
