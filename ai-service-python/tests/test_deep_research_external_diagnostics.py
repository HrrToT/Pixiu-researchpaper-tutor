import json,socket,ssl,http.client
from unittest.mock import Mock
import pytest
from services import deep_research_academic as academic
from services.deep_research.tools import ExternalAcademicAdapter
from services.deep_research.external import AcademicAcquisition
from services.deep_research.contracts import DeepResearchError
from test_deep_research_external_failures import repo,begin


@pytest.mark.parametrize('status',[301,302,307,308,403,404,429,500,502,503])
def test_http_failures_record_only_status_and_fixed_origin_without_reading_or_retry(monkeypatch,status):
    response=Mock(status=status);connection=Mock();connection.getresponse.return_value=response
    monkeypatch.setattr(academic.http.client,'HTTPSConnection',Mock(return_value=connection))
    with pytest.raises(academic.AcademicAccessError) as caught:
        academic.pinned_https_get('export.arxiv.org','/api/query?id_list=public-paper',100,resolver=lambda _:['8.8.8.8'])
    assert caught.value.transport_diagnostic=={'version':1,'origin':'metadata','category':'http_status','httpStatus':status}
    assert str(caught.value)=='学术来源暂不可获取'
    connection.request.assert_called_once();connection.close.assert_called_once();response.read.assert_not_called()


@pytest.mark.parametrize('failure,category',[(TimeoutError('private details'),'timeout'),(ssl.SSLError('private details'),'tls'),
    (ConnectionResetError('private details'),'connection'),(http.client.BadStatusLine('private details'),'protocol')])
def test_connection_categories_do_not_echo_exception_content(monkeypatch,failure,category):
    connection=Mock();connection.request.side_effect=failure
    monkeypatch.setattr(academic.http.client,'HTTPSConnection',Mock(return_value=connection))
    with pytest.raises(academic.AcademicAccessError) as caught:
        academic.pinned_https_get('arxiv.org','/pdf/2310.08528v3',100,resolver=lambda _:['8.8.8.8'])
    assert caught.value.transport_diagnostic=={'version':1,'origin':'fulltext','category':category}
    assert 'private details' not in str(caught.value)
    connection.request.assert_called_once();connection.close.assert_called_once()


def test_dns_failure_has_no_request_or_address_in_diagnostic(monkeypatch):
    connect=Mock();monkeypatch.setattr(academic.http.client,'HTTPSConnection',connect)
    with pytest.raises(academic.AcademicAccessError) as caught:
        academic.pinned_https_get('arxiv.org','/pdf/2310.08528v3',100,resolver=Mock(side_effect=socket.gaierror('private host')))
    assert caught.value.transport_diagnostic=={'version':1,'origin':'fulltext','category':'dns'}
    connect.assert_not_called()


@pytest.mark.parametrize('bad',[{'version':True,'origin':'metadata','category':'timeout'},
    {'version':1,'origin':'private host','category':'timeout'},
    {'version':1,'origin':'metadata','category':'timeout','url':'secret'},
    {'version':1,'origin':'metadata','category':'http_status','httpStatus':True},
    {'version':1,'origin':'metadata','category':'http_status','httpStatus':None},
    {'version':1,'origin':'metadata','category':'http_status','httpStatus':999}])
def test_only_bounded_trusted_diagnostic_fields_can_be_serialized(bad):
    assert academic.AcademicAccessError('fixed',transport=bad).transport_diagnostic is None


def test_diagnostic_copies_cannot_change_saved_failure_details():
    original={'version':1,'origin':'metadata','category':'http_status','httpStatus':503}
    error=academic.AcademicAccessError('fixed',transport=original)
    original['httpStatus']=200;view=error.transport_diagnostic;view['httpStatus']=200
    assert error.transport_diagnostic['httpStatus']==503


@pytest.mark.parametrize('enabled',[False,True])
def test_durable_discovery_failure_and_reopen_keep_one_send_one_budget_and_old_error_shape(repo,enabled):
    begin(repo);send=Mock(side_effect=academic.AcademicAccessError('fixed',transport={'version':1,'origin':'metadata','category':'http_status','httpStatus':503}))
    client=academic.AcademicSourceClient(academic.AcademicPolicy(enabled=True,mode='academic_external'),send)
    for _ in range(2):
        adapter=ExternalAcademicAdapter(client,repo.reserve_call,repo.complete_call,transport_diagnostics=enabled)
        assert adapter.discover('r','2310.08528v3',3)==[]
    call=repo.list_calls('r')[0];error=call['error']
    if isinstance(error,str):error=json.loads(error)
    assert error==({'message':'fixed','transportDiagnostic':{'version':1,'origin':'metadata','category':'http_status','httpStatus':503}} if enabled else {'message':'fixed'})
    send.assert_called_once();assert len(repo.list_calls('r'))==1 and repo.require_run('r')['budget']['externalSearches']==1


def test_fulltext_failure_keeps_diagnostic_without_treating_it_as_a_result():
    client=Mock();client.fetch_fulltext.side_effect=academic.AcademicAccessError('fixed',transport={'version':1,'origin':'fulltext','category':'timeout'})
    reserve=Mock(return_value=({'callId':'c','reservationToken':'t'},False));complete=Mock()
    adapter=ExternalAcademicAdapter(client,reserve,complete,transport_diagnostics=True)
    assert adapter.fetch_fulltext('r','2310.08528v3')=={}
    assert complete.call_args.kwargs['error']['transportDiagnostic']['category']=='timeout'
    assert reserve.call_args.kwargs['budget_delta']=={'fulltextFetches':1}


@pytest.mark.parametrize('value',[None,True,False,0,'1',2])
def test_server_owns_immutable_diagnostics_flag_and_does_not_migrate_legacy(tmp_path,value):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repository=DeepResearchRepository(tmp_path/'r.sqlite3');repository.initialize()
    facade=ResearchFacade(repository,lambda **_:None,llm_client=object())
    try:
        created,_=facade.create({'workspaceTaskId':'t','operationKey':'new','question':'核查','externalDiagnosticsContractVersion':value},start_async=False)
        run=repository.require_run(created['runId']);assert type(run['externalDiagnosticsContractVersion']) is int and run['externalDiagnosticsContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):repository.update_run(run['runId'],lambda r:{**r,'externalDiagnosticsContractVersion':value})
    finally:facade.shutdown()


def test_acquisition_factory_enables_diagnostics_for_new_run_and_keeps_generic_public_error(repo):
    begin(repo);repo.update_run('r',lambda r:{**r,'state':{}})
    # A legacy run cannot gain the server-owned flag after creation.
    with pytest.raises(ValueError):repo.update_run('r',lambda r:{**r,'externalDiagnosticsContractVersion':1})
    record={'runId':'new','taskId':'t','question':'public topic','sourcePolicy':{'mode':'academic_external'},'externalDiagnosticsContractVersion':1}
    repo.create_run(record);repo.begin_execution('new')
    def transport(*args):raise academic.AcademicAccessError('fixed',transport={'version':1,'origin':'metadata','category':'http_status','httpStatus':503})
    client=academic.AcademicSourceClient(academic.AcademicPolicy(enabled=True,mode='academic_external'),transport)
    acquire=AcademicAcquisition(repo,repo.complete_call,client_factory=lambda _:client)
    with pytest.raises(DeepResearchError) as caught:acquire('new',[{'obligationId':'o','query':'2310.08528v3'}])
    assert caught.value.code=='external_discovery_unavailable'
    error=repo.list_calls('new')[0]['error'];error=json.loads(error) if isinstance(error,str) else error
    assert error['transportDiagnostic']['httpStatus']==503
