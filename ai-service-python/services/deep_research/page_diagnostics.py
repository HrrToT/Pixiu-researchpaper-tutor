"""Bounded local page-resolution observations, never evidence or permissions."""
from copy import deepcopy
from time import monotonic


class PageDiagnostics:
    def __init__(self):
        self.started = monotonic()
        self.value = {'version':1,'quotes':0,'repositorySeconds':0.0,'loadSeconds':0.0,
                      'resolveSeconds':0.0,'loads':0,'cacheHits':0,'failures':{},'resolutions':{}}

    def failure(self, error):
        from services.deep_research.contracts import DeepResearchError
        import requests
        import subprocess
        if isinstance(error, DeepResearchError):
            allowed={'scope_revoked','source_changed','source_missing','source_unavailable',
                     'source_parse_failed','source_too_large'}
            code=error.code if error.code in allowed else 'source_read_failed'
        elif isinstance(error, subprocess.TimeoutExpired):code='pdf_parse_timeout'
        elif isinstance(error, requests.Timeout):code='file_request_timeout'
        else:code='file_request_failed'
        counts=self.value['failures'];counts[code]=counts.get(code,0)+1

    def resolution(self, location):
        code=location.get('pageResolution')
        if code not in {'exact','ambiguous','unresolved'}:code='retained_table_or_nonlocal'
        counts=self.value['resolutions'];counts[code]=counts.get(code,0)+1

    def snapshot(self):
        return {**deepcopy(self.value),'elapsedSeconds':monotonic()-self.started}


def enabled(record):
    return (type(record.get('physicalPageDiagnosticsContractVersion')) is int
            and record['physicalPageDiagnosticsContractVersion']==1)


def append(previous, batch):
    # Only the latest 16 local batches; no quotes, URLs, exception messages,
    # absolute file paths, credentials, or provider decisions are stored here.
    batches=(previous.get('batches',[]) if isinstance(previous,dict) and previous.get('version')==1 else [])
    return {'version':1,'batches':deepcopy(batches[-15:])+[deepcopy(batch)]}
