from unittest.mock import Mock
import pytest
from services import deep_research_academic as academic
from services import academic_proxy_transport as proxy


def response_connection(status=200, body=b'body', declared=None):
    response=Mock(status=status)
    response.getheader.side_effect=lambda name,default=None: declared if name=='Content-Length' else default
    response.read.return_value=body
    connection=Mock();connection.getresponse.return_value=response
    return connection


def test_client_proxy_is_explicit_and_ambient_proxy_does_not_enable_it(monkeypatch):
    monkeypatch.setenv('HTTPS_PROXY','http://unrelated:1234')
    assert academic.AcademicSourceClient(academic.AcademicPolicy()).transport is academic.pinned_https_get
    client=academic.AcademicSourceClient(academic.AcademicPolicy(),proxy_url='http://localhost:12450')
    assert client.transport.func is academic.pinned_https_get
    assert client.transport.keywords=={'proxy_url':'http://localhost:12450'}
    with pytest.raises(academic.AcademicAccessError):
        academic.AcademicSourceClient(academic.AcademicPolicy(),Mock(),proxy_url='http://localhost:12450')


def test_invalid_proxy_is_rejected_without_network_or_credential_echo():
    with pytest.raises(academic.AcademicAccessError,match='配置无效') as caught:
        academic.AcademicSourceClient(academic.AcademicPolicy(),proxy_url='http://user:secret@localhost:1')
    assert 'secret' not in str(caught.value)


@pytest.mark.parametrize('status,body,declared',[(302,b'',None),(200,b'x'*11,None),(200,b'', '11')])
def test_proxy_route_retains_redirect_and_response_size_guards(monkeypatch,status,body,declared):
    conn=response_connection(status,body,declared);factory=Mock(return_value=conn)
    monkeypatch.setattr(proxy,'proxy_https_connection',factory)
    with pytest.raises(academic.AcademicAccessError):
        academic.pinned_https_get('arxiv.org','/pdf/2403.17888v3',10,
            resolver=lambda _:['8.8.8.8'],proxy_url='http://localhost:12450')
    factory.assert_called_once_with('http://localhost:12450','arxiv.org','8.8.8.8',timeout=20)
    conn.request.assert_called_once();conn.close.assert_called_once()


@pytest.mark.parametrize('host,path,addresses',[
    ('localhost','/api/query?x=1',['8.8.8.8']),
    ('arxiv.org','/pdf/2403.17888v3',['8.8.8.8','127.0.0.1']),
    ('arxiv.org','/api/query?x=1',['8.8.8.8']),
])
def test_proxy_does_not_expand_allowed_origin_or_public_address_scope(monkeypatch,host,path,addresses):
    factory=Mock();monkeypatch.setattr(proxy,'proxy_https_connection',factory)
    with pytest.raises(academic.AcademicAccessError):
        academic.pinned_https_get(host,path,100,resolver=lambda _:addresses,proxy_url='http://localhost:12450')
    factory.assert_not_called()


def test_proxy_route_sends_exactly_one_original_request(monkeypatch):
    conn=response_connection();monkeypatch.setattr(proxy,'proxy_https_connection',Mock(return_value=conn))
    _,body=academic.pinned_https_get('export.arxiv.org','/api/query?id_list=2403.17888v3',10,
        resolver=lambda _:['8.8.8.8'],proxy_url='http://localhost:12450')
    assert body==b'body'
    assert conn.request.call_args.args==('GET','/api/query?id_list=2403.17888v3')
    conn.request.assert_called_once();conn.close.assert_called_once()


def test_production_acquisition_factory_uses_operator_setting(monkeypatch):
    from services.deep_research.external import AcademicAcquisition
    from core.config import settings
    monkeypatch.setattr(settings,'deep_research_http_proxy','http://host.docker.internal:12450')
    client=AcademicAcquisition(Mock(),Mock())._client({'sourcePolicy':{'mode':'task_only'}})
    assert client.transport.keywords['proxy_url']=='http://host.docker.internal:12450'
    with pytest.raises(academic.AcademicAccessError):client.discover('topic')
