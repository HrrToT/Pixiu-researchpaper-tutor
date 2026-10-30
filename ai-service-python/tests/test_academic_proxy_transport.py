from unittest.mock import Mock
import ssl
import pytest
from services.academic_proxy_transport import AcademicProxyError,proxy_endpoint,proxy_https_connection


@pytest.mark.parametrize('url',['','socks5://localhost:7890','https://localhost:7890',
    'http://user:secret@localhost:7890','http://@localhost:7890','http://:@localhost:7890','http://localhost','http://localhost:0',
    'http://localhost:65536','http://localhost:7890/path','http://localhost:7890?q=1',
    'http://localhost:7890#x','http://local\nhost:7890',' http://localhost:7890'])
def test_invalid_or_credentialed_proxy_never_leaks_input(url):
    with pytest.raises(AcademicProxyError) as error:proxy_endpoint(url)
    assert 'secret' not in str(error.value) and 'http://' not in str(error.value)


def test_explicit_local_operator_proxy_is_allowed_but_origin_private_ips_are_not():
    assert proxy_endpoint('http://127.0.0.1:7890')==('127.0.0.1',7890)
    assert proxy_endpoint('http://host.docker.internal:7890/')==('host.docker.internal',7890)
    for address in ['127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:127.0.0.1']:
        with pytest.raises(AcademicProxyError,match='不可访问'):
            proxy_https_connection('http://localhost:7890','arxiv.org',address)
    with pytest.raises(AcademicProxyError,match='允许范围'):
        proxy_https_connection('http://localhost:7890','private.example','8.8.8.8')


def test_tunnel_pins_public_ip_but_tls_and_http_host_keep_original_origin(monkeypatch):
    from services import academic_proxy_transport as module
    connection=proxy_https_connection('http://localhost:7890','export.arxiv.org','8.8.8.8')
    assert connection.host=='localhost' and connection.port==7890
    assert connection._tunnel_host=='8.8.8.8' and connection._tunnel_port==443
    assert connection._context.check_hostname and connection._context.verify_mode==ssl.CERT_REQUIRED
    raw=object();wrapped=object();connects=[]
    def connect(self):
        connects.append((self.host,self.port,self._tunnel_host,self._tunnel_port));self.sock=raw
    monkeypatch.setattr(module.http.client.HTTPConnection,'connect',connect)
    context=Mock();context.wrap_socket.return_value=wrapped;connection._context=context
    connection.connect()
    assert connects==[('localhost',7890,'8.8.8.8',443)]
    context.wrap_socket.assert_called_once_with(raw,server_hostname='export.arxiv.org')
    assert connection.sock is wrapped
    request=Mock();monkeypatch.setattr(module.http.client.HTTPSConnection,'request',request)
    headers={'Accept-Encoding':'identity'}
    connection.request('GET','/api/query?id_list=2403.17888',headers=headers)
    assert request.call_args.args[3]['Host']=='export.arxiv.org'
    assert headers=={'Accept-Encoding':'identity'}
    with pytest.raises(AcademicProxyError,match='身份'):
        connection.request('GET','/api/query?',headers={'Host':'localhost'})
    with pytest.raises(AcademicProxyError,match='身份'):
        connection.request('GET','/api/query?',headers={'Host':'export.arxiv.org','host':'export.arxiv.org'})
