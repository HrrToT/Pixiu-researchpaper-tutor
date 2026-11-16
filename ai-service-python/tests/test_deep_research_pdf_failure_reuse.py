from copy import deepcopy
from types import SimpleNamespace
import json
import subprocess
from unittest.mock import Mock

import pytest
import requests

from services.deep_research.contracts import DeepResearchError
from services.deep_research.located_evidence import located_evidence_factory
from services.deep_research.source_passage_reuse import failure_reuse_enabled
from services.deep_research.pdf_worker_errors import encode_failure,details
from test_deep_research_located_evidence import setup,QUOTE


def factory(cache=True):
    _,source,record,local=setup();repo=Mock();repo.require_run.return_value=record
    return located_evidence_factory(repo,'run',local,cache_failed_batches=cache),source,record,local


def test_definite_parse_failure_is_attempted_once_per_unchanged_pdf_per_batch():
    create,source,record,local=factory();success=local.load_pages.return_value
    local.load_pages.side_effect=[DeepResearchError('source_parse_failed','private detail',
        {'workerExitCode':2,'workerFailureKind':'PdfReadError'}),success]
    args=dict(location={'page':1},obligation_ids=['o'])
    with create.physical_page_batch():
        results=[create(source,QUOTE,QUOTE,**args) for _ in range(30)]
    assert local.load_pages.call_count==1
    assert all(r==results[0] and r['location']['pageResolution']=='unresolved' and 'page' not in r['location'] for r in results)
    assert results[0]['verification']=={'literal':'passed','semantic':'unchecked'}
    audit=create.physical_page_diagnostics()
    assert audit['failures']=={'source_parse_failed':1} and audit['failedCacheHits']==29
    assert audit['workerFailures']=={'PdfReadError':1} and audit['workerExitCodes']=={'2':1}
    assert 'private' not in json.dumps(audit)
    with create.physical_page_batch():assert create(source,QUOTE,QUOTE,**args)['location']['page']==2
    assert local.load_pages.call_count==2


@pytest.mark.parametrize('error',[
    requests.Timeout('private'),subprocess.TimeoutExpired('private command',20),
    DeepResearchError('source_unavailable','private')])
def test_transient_file_and_timeout_failures_still_can_recover_inside_batch(error):
    create,source,_,local=factory();local.load_pages.side_effect=[error,local.load_pages.return_value]
    with create.physical_page_batch():
        assert create(source,QUOTE,QUOTE,location={},obligation_ids=['o'])['location']['pageResolution']=='unresolved'
        assert create(source,QUOTE,QUOTE,location={},obligation_ids=['o'])['location']['page']==2
    assert local.load_pages.call_count==2 and not create.physical_page_diagnostics()['failedCacheHits']


def test_old_policy_still_retries_a_parse_failure():
    create,source,_,local=factory(False)
    local.load_pages.side_effect=[DeepResearchError('source_parse_failed','failed'),local.load_pages.return_value]
    with create.physical_page_batch():
        create(source,QUOTE,QUOTE,location={},obligation_ids=['o'])
        assert create(source,QUOTE,QUOTE,location={},obligation_ids=['o'])['location']['page']==2
    assert local.load_pages.call_count==2


def test_failure_reuse_is_never_active_outside_the_scoped_batch():
    create,source,_,local=factory()
    local.load_pages.side_effect=[DeepResearchError('source_parse_failed','failed'),local.load_pages.return_value]
    create(source,QUOTE,QUOTE,location={},obligation_ids=['o'])
    assert create(source,QUOTE,QUOTE,location={},obligation_ids=['o'])['location']['page']==2
    assert local.load_pages.call_count==2


def test_failure_reuse_never_crosses_pdf_owner_or_changed_snapshot_hash():
    create,source,record,local=factory()
    record['materials'].append({**record['materials'][0],'materialId':'other'})
    local.load_pages.side_effect=[DeepResearchError('source_parse_failed','failed'),
        (None,[{'page':7,'text':QUOTE}]),DeepResearchError('source_changed','changed')]
    with create.physical_page_batch():
        create(source,QUOTE,QUOTE,location={},obligation_ids=['o'])
        assert create({**source,'workId':'other'},QUOTE,QUOTE,location={},obligation_ids=['o'])['location']['page']==7
        record['materials'][0]['contentHash']='new-snapshot'
        with pytest.raises(DeepResearchError,match='changed'):
            create(source,QUOTE,QUOTE,location={},obligation_ids=['o'])
    assert local.load_pages.call_count==3


@pytest.mark.parametrize('code',['scope_revoked','source_changed','source_missing'])
def test_authority_failures_are_never_swallowed(code):
    create,source,_,local=factory();local.load_pages.side_effect=DeepResearchError(code,'revoked')
    with pytest.raises(DeepResearchError):
        with create.physical_page_batch():create(source,QUOTE,QUOTE,location={},obligation_ids=['o'])


def test_failure_policy_requires_exact_new_server_version_and_canonical_extraction():
    for version in [None,0,1,True,'2',2.0,3]:
        assert not failure_reuse_enabled({'sourcePassageReuseContractVersion':version,'adaptiveExtractionContractVersion':3})
    assert failure_reuse_enabled({'sourcePassageReuseContractVersion':2,'adaptiveExtractionContractVersion':3})
    assert not failure_reuse_enabled({'sourcePassageReuseContractVersion':2,'adaptiveExtractionContractVersion':2})


def test_worker_tags_never_forward_exception_text_or_unrecognized_tags():
    assert encode_failure(ValueError('private token'))=='PIXIU_PDF_PARSE_ERROR:ValueError\n'
    class SecretException(Exception):pass
    assert encode_failure(SecretException('private'))=='PIXIU_PDF_PARSE_ERROR:ParserError\n'
    for stderr,kind in [(b'PIXIU_PDF_PARSE_ERROR:PdfReadError\n','PdfReadError'),
                        (b'private Traceback: path and PDF text','worker_exit'),
                        (b'PIXIU_PDF_PARSE_ERROR:SecretException\n','worker_exit'),
                        (b'PIXIU_PDF_PARSE_ERROR:ValueError\nPIXIU_PDF_PARSE_ERROR:PdfReadError\n','worker_exit')]:
        result=details(SimpleNamespace(returncode=2,stderr=stderr))
        assert result=={'workerExitCode':2,'workerFailureKind':kind} and 'private' not in json.dumps(result)


def test_real_malformed_worker_returns_safe_error_category_without_pdf_text():
    from services.deep_research.local_sources import _parse_pdf
    with pytest.raises(DeepResearchError) as result:_parse_pdf(b'%PDF-1.7\nPRIVATE-DOCUMENT-PAYLOAD\n')
    assert result.value.code=='source_parse_failed'
    assert result.value.details['workerExitCode']==2
    assert result.value.details['workerFailureKind']=='PdfReadError'
    assert 'PRIVATE' not in json.dumps(result.value.details)


def test_reused_failure_cannot_publish_if_scope_is_revoked_at_checkpoint(tmp_path):
    from test_deep_research_source_passages import fixture
    from test_deep_research_adaptive_extraction import activate
    from services.deep_research.source_passages import extract
    repo,_,reads=fixture(tmp_path)
    repo=activate(repo,adaptiveExtractionContractVersion=3,sourcePassageReuseContractVersion=2)
    source=deepcopy(reads[0]);source['pages']=[{'text':'First sentence. Second sentence. Third sentence. Fourth sentence.'}]
    repo.update_run('r',lambda r:{**r,'materials':[{'materialId':source['workId'],'contentHash':'pdf'}],
        'state':{**r['state'],'readResults':[source]}})
    local=Mock();local.load_pages.side_effect=DeepResearchError('source_parse_failed','failed')
    create=located_evidence_factory(repo,'r',local,cache_failed_batches=True)
    class Scope:
        calls=0
        def validate_materials(self,*args):self.calls+=1;return self.calls==1
    before=deepcopy(repo.require_run('r')['state'])
    with pytest.raises(DeepResearchError,match='未保存'):
        extract(repo.require_run('r'),create,Scope(),repo.update_run)
    assert local.load_pages.call_count==1 and repo.require_run('r')['state']==before
