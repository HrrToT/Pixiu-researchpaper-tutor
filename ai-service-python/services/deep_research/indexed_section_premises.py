"""Allocate already-read indexed section fragments without assembling quotations."""
from collections import Counter
import hashlib
import re


def bundle(rows, read_sources, work, sections):
    if not isinstance(work, str) or not work:
        return []
    sources = {}
    counts = Counter(s.get('sourceId') for s in read_sources if isinstance(s, dict) and isinstance(s.get('sourceId'), str))
    for source in read_sources:
        if not isinstance(source, dict) or not isinstance(source.get('location'), dict):
            continue
        sid = source.get('sourceId');loc = source.get('location') or {}
        index = loc.get('chunk');page = loc.get('page');section = loc.get('section')
        text = source.get('text');version = source.get('versionId')
        match = re.fullmatch(re.escape(work) + r'-v([0-9a-f]{16})-chunk-(\d+)', str(sid))
        if (not match or counts[sid] != 1 or type(index) is not int or index != int(match[2])
                or type(page) is not int or page < 1 or not isinstance(section, str) or not section.strip()
                or source.get('workId') != work or source.get('ownerMaterialId') != work
                or source.get('accessLevel') != 'fulltext' or not isinstance(version, str) or not version
                or not isinstance(text, str) or not text
                or hashlib.sha256(text.encode()).hexdigest() != source.get('contentHash')):
            continue
        body = re.search(r'\bContent:\s*', text)
        if body is None:
            continue
        candidates = []
        for row in rows:
            if (not isinstance(row, dict) or not isinstance(row.get('location'), dict)
                    or not isinstance(row.get('verification'), dict)
                    or not isinstance(row.get('evidenceId'), str) or not row['evidenceId']):
                continue
            location = row.get('location') or {};a = location.get('sourcePassageStart');b = location.get('sourcePassageEnd')
            if (row.get('sourceId') != sid or row.get('sourceWorkId') != work
                    or row.get('ownerMaterialId', work) != work or row.get('sourceVersionId') != version
                    or row.get('contentHash') != source['contentHash'] or row.get('accessLevel') != 'fulltext'
                    or row.get('verification', {}).get('literal') != 'passed'
                    or type(a) is not int or type(b) is not int or not body.end() <= a < b <= len(text)
                    or text[a:b] != row.get('quote')):
                continue
            candidates.append((a, b, row))
        candidates.sort(key=lambda item: item[0])
        if (not candidates or text[body.end():candidates[0][0]].strip()
                or text[candidates[-1][1]:].strip()
                or any(left[1] > right[0] or text[left[1]:right[0]].strip() for left, right in zip(candidates, candidates[1:]))
                or len({r[2].get('evidenceId') for r in candidates}) != len(candidates)):
            continue
        sources[(match[1], version, section, index)] = (source, [r[2] for r in candidates], text[body.end():])
    for (index_version, version, section, index), (source, evidence, text) in sources.items():
        if not any(re.match(r'\s*' + re.escape(target) + r'\s+(?=[A-Z\u4e00-\u9fff])', text) for target in sections):
            continue
        result = list(evidence);page = source['location']['page']
        for step in (1, 2):
            following = sources.get((index_version, version, section, index + step))
            if following is None:
                break
            next_page = following[0]['location']['page']
            if not page <= next_page <= page + 1 or len(result) + len(following[1]) > 10:
                break
            result.extend(following[1]);page = next_page
        if len(result) <= 10:
            return result
    return []
