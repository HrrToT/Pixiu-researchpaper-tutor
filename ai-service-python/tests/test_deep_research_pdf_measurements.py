import hashlib
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import Mock

import pytest
import requests

from services.deep_research.contracts import DeepResearchError
from services.deep_research.local_sources import LocalTaskRetriever
from services.deep_research.requested_measurements import include_pdf_measurements, missing_measurements


def setup(monkeypatch, *, version=3):
    from services.tools import retrieval_tools
    body=b'%PDF-owned-original'; digest=hashlib.sha256(body).hexdigest()
    repo=Mock(); repo.require_run.return_value={'taskId':'task/中文','sourcePrecisionContractVersion':version,
        'materials':[{'materialId':'p','contentHash':digest,'versionId':'original-v1','title':'Paper'}]}
    validate=Mock(return_value=True)
    response=Mock(status_code=200); response.iter_content.return_value=[body]
    response.__enter__=Mock(return_value=response); response.__exit__=Mock(return_value=False)
    get=Mock(return_value=response)
    parse=Mock(return_value=[{'page':1,'text':'Original reconstruction takes 17 seconds per frame, followed by rendering at 140 FPS.'}])
    def item(index,text):
        return {'text':text,'metadata':{'id':'p','index_version':'a'*16,'chunk_index':index,'section_title':'Conclusion','page':8}}
    top=item(9,'Training takes 15 seconds and rendering reaches 140 FPS.')
    low=item(10,'General benchmark overview without the requested duration.')
    rag=Mock(); rag.normalize_id.side_effect=lambda x:x; rag.get_documents_by_metadata.return_value=[top,low]
    retrieve=Mock(return_value=[top,low])
    monkeypatch.setattr('services.deep_research.local_sources.importlib.util.find_spec',lambda _:object())
    monkeypatch.setattr(retrieval_tools,'get_rag',lambda:rag)
    monkeypatch.setattr(retrieval_tools,'retrieve_fused_evidence',retrieve)
    local=LocalTaskRetriever(repo,'r',validate,origin='http://127.0.0.1:8081/api',get=get,parse=parse)
    return local,repo,validate,get,parse,response,rag,retrieve


def test_missing_index_value_reaches_the_result_from_exact_owned_pdf_with_independent_identity(monkeypatch):
    local,repo,validate,get,parse,response,rag,retrieve=setup(monkeypatch)
    found=local('17 seconds reconstruction 140 FPS','p',limit=2)
    assert len(found)==2 and found[0]['chunkIndex']==9
    original=found[1]
    assert original['text']==parse.return_value[0]['text']
    assert original['location']=={'page':1,'offset':0} and original['sourceId'].startswith('src_')
    assert original['contentHash']==repo.require_run.return_value['materials'][0]['contentHash']
    assert original['versionId']=='original-v1' and original['retrievalMode']=='pdf_requested_measurement'
    assert not missing_measurements(found,'17s 140FPS')
    assert found[0]['pdfMeasurementRead']=={'status':'searched','pagesRead':1,'unmatchedMeasurements':[]}
    assert '/task%2F%E4%B8%AD%E6%96%87/materials/p/file' in get.call_args.args[0]
    assert get.call_args.kwargs=={'timeout':20,'stream':True,'allow_redirects':False}
    assert local('17 seconds reconstruction 140 FPS','p',limit=2)==found
    assert get.call_count==parse.call_count==1
    validate.return_value=False
    with pytest.raises(DeepResearchError,match='范围'):local('17s 140FPS','p',limit=2)
    assert retrieve.call_count==2


@pytest.mark.parametrize('version',[1,2])
def test_older_precision_versions_do_not_fetch_original_for_index_hits(monkeypatch,version):
    local,_,_,get,parse,*_=setup(monkeypatch,version=version)
    found=local('17s 140FPS','p',limit=2)
    assert [r['chunkIndex'] for r in found]==[9,10]
    assert all('pdfMeasurementRead' not in r for r in found)
    get.assert_not_called(); parse.assert_not_called()


def test_complete_index_measurement_does_not_need_pdf_supplement(monkeypatch):
    local,_,_,get,parse,_,rag,_=setup(monkeypatch)
    exact={'text':'Reconstruction takes 17 seconds with rendering at 140 FPS.',
        'metadata':{'id':'p','index_version':'a'*16,'chunk_index':0,'section_title':'Abstract','page':1}}
    rag.get_documents_by_metadata.return_value.append(exact)
    found=local('17s 140FPS','p',limit=2)
    assert [r['chunkIndex'] for r in found]==[9,0]
    get.assert_not_called(); parse.assert_not_called()


@pytest.mark.parametrize('error,code',[
    (DeepResearchError('source_parse_failed','fixture'),'source_parse_failed'),
    (requests.ReadTimeout('fixture'),'source_unavailable'),
    (subprocess.TimeoutExpired('fixture',20),'source_parse_timeout'),
])
def test_known_optional_read_failures_keep_index_and_are_not_retried(monkeypatch,error,code):
    local,_,_,get,parse,*_=setup(monkeypatch)
    parse.side_effect=error
    first=local('17s 140FPS','p',limit=2)
    second=local('17 seconds reconstruction 140FPS','p',limit=2)
    assert [r['chunkIndex'] for r in first]==[9,10]
    assert first[0]['pdfMeasurementRead']==second[0]['pdfMeasurementRead']=={'status':'unavailable','code':code}
    assert get.call_count==parse.call_count==1


@pytest.mark.parametrize('status',[401,403])
def test_file_access_rejection_is_not_hidden_as_optional_index_success(monkeypatch,status):
    local,_,_,get,parse,response,*_=setup(monkeypatch)
    response.status_code=status
    with pytest.raises(DeepResearchError) as error:local('17s 140FPS','p',limit=2)
    assert error.value.code=='source_unavailable' and error.value.details['status_code']==status
    assert get.call_count==1
    parse.assert_not_called()


def test_changed_file_hash_stops_even_with_usable_old_index(monkeypatch):
    local,_,_,get,parse,response,*_=setup(monkeypatch)
    response.iter_content.return_value=[b'%PDF-changed']
    with pytest.raises(DeepResearchError) as error:local('17s 140FPS','p',limit=2)
    assert error.value.code=='source_changed'
    assert not local._measurement_read_failures
    parse.assert_not_called()


def test_permission_revoked_during_parse_is_checked_before_returning_sources(monkeypatch):
    local,_,validate,get,parse,*_=setup(monkeypatch)
    def revoke(body):
        validate.return_value=False
        return [{'page':1,'text':'Reconstruction takes 17 seconds with rendering at 140 FPS.'}]
    parse.side_effect=revoke
    with pytest.raises(DeepResearchError) as error:local('17s 140FPS','p',limit=2)
    assert error.value.code=='scope_revoked' and get.call_count==1


def test_pdf_byte_limit_stops_before_parser_and_preserves_index_with_read_limit(monkeypatch):
    local,_,_,get,parse,*_=setup(monkeypatch)
    monkeypatch.setattr('services.deep_research.local_sources.MAX_LOCAL_PDF_BYTES',8)
    found=local('17s 140FPS','p',limit=2)
    assert found[0]['pdfMeasurementRead']['code']=='source_too_large'
    assert get.call_count==1
    parse.assert_not_called()


def test_concurrent_queries_share_one_hash_checked_pdf_parse(monkeypatch):
    local,_,_,get,parse,*_=setup(monkeypatch)
    entered=threading.Event(); release=threading.Event()
    def delayed(body):
        entered.set()
        assert release.wait(3)
        return [{'page':1,'text':'Reconstruction takes 17 seconds with rendering at 140 FPS.'}]
    parse.side_effect=delayed
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(local,'17s 140FPS','p',limit=2)
        try:
            assert entered.wait(3)
            second=pool.submit(local,'17 seconds 140 FPS','p',limit=2)
        finally:release.set()
        a,b=first.result(timeout=5),second.result(timeout=5)
    assert a[1]['sourceId']==b[1]['sourceId'] and get.call_count==parse.call_count==1


def test_pdf_selector_rejects_other_owner_hash_and_preserves_context_sources():
    top={'sourceId':'top','pdfId':'p','metadata':{'id':'p'},'text':'Overview'}
    prev={'sourceId':'prev','pdfId':'p','metadata':{'id':'p'},'text':'Context','contextForSourceId':'top'}
    low={'sourceId':'low','pdfId':'p','metadata':{'id':'p'},'text':'Other'}
    raw={'sourceId':'raw','pdfId':'p','contentHash':'hash','text':'17 seconds',
         'location':{'page':1,'offset':1500},'versionId':'v'}
    before=deepcopy([top,prev,low,raw])
    assert include_pdf_measurements([top,prev,low],[{**raw,'pdfId':'foreign'},{**raw,'contentHash':'different'}],
                                    '17s','p','hash',3)==[top,prev,low]
    found=include_pdf_measurements([top,prev,low],[raw],'17s','p','hash',3)
    assert {r['sourceId'] for r in found}=={'top','prev','raw'} and len(found)==3
    assert found[1]['text']==raw['text'] and found[1]['location']==raw['location']
    assert [top,prev,low,raw]==before


@pytest.mark.parametrize('version',[1,2,3])
def test_foreign_backend_hit_is_never_accepted_as_owned_index_text(monkeypatch,version):
    local,_,_,get,parse,_,_,retrieve=setup(monkeypatch,version=version)
    retrieve.return_value=[{'text':'Foreign private answer with 17 seconds and 140 FPS.',
        'metadata':{'id':'foreign','index_version':'a'*16,'chunk_index':1,'section_title':'Other'}}]
    found=local('17 seconds reconstruction 140 FPS','p',limit=2)
    assert found and all('Foreign private' not in r['text'] for r in found)
    assert all(r['pdfId']=='p' for r in found) and get.call_count==parse.call_count==1
