"""Explicit operator HTTP proxy for a public-IP-pinned arXiv TLS tunnel.

This module does not consult ambient proxies or retry. Origin allowlisting,
redirect rejection, response limits and request budgets also remain enforced
by the academic caller. No connection is made merely by constructing it.
"""
import http.client
import ipaddress
import ssl
from urllib.parse import urlsplit


class AcademicProxyError(ValueError):
    """Fixed errors only; never echo a proxy URL or credentials."""


def proxy_endpoint(value):
    if (not isinstance(value,str) or not value or len(value)>1000
            or any(ord(c)<=32 or ord(c)==127 for c in value)):
        raise AcademicProxyError('学术代理配置无效')
    try:
        parsed=urlsplit(value)
        valid=(parsed.scheme=='http' and parsed.hostname and parsed.port
               and parsed.username is None and parsed.password is None
               and parsed.path in ('','/') and not parsed.query and not parsed.fragment)
        if valid:return parsed.hostname,parsed.port
    except ValueError:pass
    raise AcademicProxyError('学术代理仅支持无认证的HTTP地址及明确端口')


class _PinnedProxyConnection(http.client.HTTPSConnection):
    def __init__(self,proxy_host,proxy_port,origin_host,target_ip,timeout):
        super().__init__(proxy_host,proxy_port,timeout=timeout,context=ssl.create_default_context())
        self._academic_origin=origin_host
        self.set_tunnel(target_ip,443)

    def connect(self):
        # The standard HTTP layer opens the configured proxy and CONNECTs the
        # literal pinned public IP. TLS still verifies the original arXiv name,
        # never the proxy name or the target-IP certificate identity.
        http.client.HTTPConnection.connect(self)
        self.sock=self._context.wrap_socket(self.sock,server_hostname=self._academic_origin)

    def request(self,method,url,body=None,headers=None,*,encode_chunked=False):
        headers=dict(headers or {})
        hosts=[value for key,value in headers.items() if key.lower()=='host']
        if len(hosts)>1 or any(value!=self._academic_origin for value in hosts):
            raise AcademicProxyError('学术来源主机身份不一致')
        if not hosts:headers['Host']=self._academic_origin
        return super().request(method,url,body,headers,encode_chunked=encode_chunked)


def proxy_https_connection(proxy_url,origin_host,target_ip,*,timeout=20):
    """The proxy is trusted operator config; the origin remains public/pinned."""
    if origin_host not in ('arxiv.org','export.arxiv.org'):
        raise AcademicProxyError('学术来源超出允许范围')
    try:public=ipaddress.ip_address(target_ip).is_global
    except (TypeError,ValueError):public=False
    if not public:raise AcademicProxyError('学术来源地址不可访问')
    host,port=proxy_endpoint(proxy_url)
    return _PinnedProxyConnection(host,port,origin_host,target_ip,timeout)
