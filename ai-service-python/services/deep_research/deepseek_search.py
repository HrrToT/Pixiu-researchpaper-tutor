"""Use web search to locate arXiv PDFs without admitting search text as evidence."""
from __future__ import annotations

import json
import re
from time import monotonic, time

import requests

from services.deep_research.source_revisions import work_id
from services.deep_research_academic import AcademicAccessError, checked_arxiv_id


SEARCH_URL = 'https://api.deepseek.com/v1/tools/search'
MAX_RESPONSE_BYTES = 512 * 1024
ARXIV_URL = re.compile(r'https?://arxiv\.org/(?:abs|pdf|html)/([^?#]+)(?:[?#].*)?')


def read_search_results(api_key, query, count):
    deadline = monotonic() + 10
    try:
        with requests.post(SEARCH_URL, headers={'Authorization': f'Bearer {api_key}'},
                           json={'query': query, 'count': count, 'need_content': False},
                           allow_redirects=False, stream=True, timeout=(4, 4)) as response:
            if response.status_code != 200:
                raise AcademicAccessError(f'DeepSeek 搜索失败（HTTP {response.status_code}）')
            body = bytearray()
            for chunk in response.iter_content(8192):
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES or monotonic() > deadline:
                    raise AcademicAccessError('DeepSeek 搜索响应超过读取限制')
        payload = json.loads(body)
    except (requests.RequestException, ValueError) as exc:
        if isinstance(exc, AcademicAccessError):
            raise
        raise AcademicAccessError('DeepSeek 搜索响应不可用') from None
    if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
        raise AcademicAccessError('DeepSeek 搜索响应格式无效')
    return payload['results'][:count]


class DeepSeekAcademicSearch:
    def __init__(self, api_key):
        self.api_key = api_key

    def __call__(self, query, limit, *, include_unversioned=False):
        # Do not send the original question or request crawled document text.
        results = read_search_results(self.api_key, 'site:arxiv.org ' + query[:113], limit)
        candidates = {}
        for item in results:
            url = item.get('url') if isinstance(item, dict) else None
            match = ARXIV_URL.fullmatch(url) if isinstance(url, str) else None
            if not match:
                continue
            try:
                identity = checked_arxiv_id(match[1].removesuffix('.pdf'))
            except AcademicAccessError:
                continue
            work = work_id(identity)
            if work == identity:
                if include_unversioned:
                    candidates.setdefault(identity, {'unresolvedArxivWork': work})
                continue
            title = item.get('title')
            candidates.setdefault(identity, {
                'arxivId': identity,
                'workId': 'arxiv:' + work,
                'versionId': 'arxiv:' + identity,
                'url': 'https://arxiv.org/abs/' + identity,
                'title': title[:1000] if isinstance(title, str) else identity,
                'retrievedAt': time(),
                'discoveryProvider': 'deepseek_search',
            })
        return list(candidates.values())
