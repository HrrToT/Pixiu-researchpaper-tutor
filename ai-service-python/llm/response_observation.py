"""Bounded HTTP receipts only: no arbitrary headers, bodies or reasoning text.

Headers are not proof that a generation completed. Freeze before returning to
the caller so a late deadline worker cannot alter persisted evidence.
"""
from copy import deepcopy
import re
from threading import Lock
from time import monotonic

OPTION = '_deepseek_observe_headers'
_ID = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')


def sanitize(value):
    if (not isinstance(value,dict) or type(value.get('version')) is not int or value['version']!=1
            or type(value.get('headersReceived')) is not bool or type(value.get('bodyReceived')) is not bool):
        return None
    headers=value['headersReceived'];body=value['bodyReceived']
    if body and not headers:return None
    result={'version':1,'headersReceived':headers,'bodyReceived':body,
        'phase':'body_received' if body else 'headers_received' if headers else 'no_headers_observed'}
    if headers:
        status=value.get('httpStatus')
        if type(status) is not int or not 100<=status<=599:return None
        result['httpStatus']=status
        identifier=value.get('requestId')
        if isinstance(identifier,str) and _ID.fullmatch(identifier):result['requestId']=identifier
    for key,allowed in (('headersElapsedMs',headers),('bodyElapsedMs',body)):
        elapsed=value.get(key)
        if allowed and type(elapsed) is int and 0<=elapsed<=86400000:result[key]=elapsed
    return result


class Observation:
    def __init__(self):
        self._started=monotonic();self._lock=Lock();self._frozen=False
        self._value={'version':1,'headersReceived':False,'bodyReceived':False}

    def headers(self,response):
        status=response.status_code
        if type(status) is not int or not 100<=status<=599:return
        with self._lock:
            if self._frozen:return
            self._value.update(headersReceived=True,httpStatus=status,
                headersElapsedMs=max(0,int((monotonic()-self._started)*1000)))
        # Never hold the freeze lock while touching provider-owned headers.
        headers=getattr(response,'headers',{})
        if isinstance(headers,dict) or callable(getattr(headers,'get',None)):
            for name in ('x-request-id','x-ds-request-id'):
                try:
                    identifier=headers.get(name)
                except Exception:continue
                if isinstance(identifier,str) and _ID.fullmatch(identifier):
                    with self._lock:
                        if not self._frozen:self._value['requestId']=identifier
                    break

    def body(self):
        with self._lock:
            if not self._frozen and self._value['headersReceived']:
                self._value.update(bodyReceived=True,bodyElapsedMs=max(0,int((monotonic()-self._started)*1000)))

    def freeze(self):
        with self._lock:
            self._frozen=True
            return deepcopy(sanitize(self._value))


class PreparedResponse:
    def __init__(self,status,data=None,invalid_json=False):
        self.status_code=status;self._data=data;self._invalid_json=invalid_json

    def json(self):
        if self._invalid_json:raise ValueError('Invalid provider JSON')
        return self._data


def read_json(post,observation,*,include_error=False):
    """Run header receipt AND full body read inside the caller's one deadline."""
    response=post()
    try:
        observation.headers(response)
        if response.status_code>=400 and not include_error:return PreparedResponse(response.status_code)
        try:data=response.json()
        except ValueError:
            observation.body();return PreparedResponse(response.status_code,invalid_json=True)
        observation.body()
        return PreparedResponse(response.status_code,data)
    finally:
        try:response.close()
        except Exception:pass
