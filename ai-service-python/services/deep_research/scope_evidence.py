"""Reserve an existing passage slot for requested scientific conditions.

Ranking is not evidence approval. Never create a passage, alter a quotation,
expand scope, or displace explicit measurements/context bundles.
"""
from collections import Counter
import re

from services.deep_research.criterion_sources import acquisition_questions
from services.deep_research.source_continuity import _body, _exact_indexed

_ASK = re.compile(r'成立条件|适用条件|适用范围|未验证范围|泛化|局限|敏感性|消融|适用边界|'
                  r'\b(?:conditions?|limitations?|scope|generaliz\w*|sensitiv\w*|ablat\w*)\b', re.I)
_OUTCOME = re.compile(r'\b(?:qualit\w*|accura\w*|errors?|performance|yields?|latency|loss|'
                      r'success\w*|fail\w*|degrad\w*)\b|质量|精度|误差|性能|产率|延迟|损失|退化', re.I)
_SETTING = re.compile(r'\b(?:when|under|if|at|with|as)\b[^.!?\n]{0,180}?\d|'
                      r'(?:当|在|如果|随着)[^。！？\n]{0,100}?\d', re.I)
_STUDY = re.compile(r'\b(?:ablat\w*|sensitiv\w*|vary\w*|varied)\b|消融|敏感性|变化', re.I)
_CHANGE = re.compile(r'\b(?:increas\w*|decreas\w*|reduc\w*|declin\w*|reach\w*|lower\w*|'
                     r'degrad\w*|improv\w*)\b|下降|提高|降低|退化', re.I)


def enabled(record):
    return (type(record.get('scopeEvidenceContractVersion')) is int
            and record['scopeEvidenceContractVersion'] == 1)


def condition_score(row):
    # A paper title or a copied section label cannot establish passage content.
    prose='\n'.join(line for line in _body(row).splitlines()
                    if not re.match(r'^\s*Table row\s+\d+:',line,re.I))
    sentences=re.split(r'(?<!\d)[.!?](?!\d)|[。！？\n]',prose)
    pairs=sum(bool(_SETTING.search(s) and _OUTCOME.search(s)) for s in sentences)
    if not pairs:
        return (0,0,0)
    return (min(3,pairs),int(bool(_STUDY.search(prose))),min(3,len(set(m.group().lower() for m in _CHANGE.finditer(prose)))))


def include_scope_evidence(indexed,candidates,record,query,owner,limit,*,content_hash=None):
    selected=list(indexed[:max(0,limit)])
    if (limit<2 or not selected or not enabled(record)
            or not any(_ASK.search(q) for q in acquisition_questions(record,query,owner))):
        return selected
    if any(not isinstance(r,dict) for r in selected):
        return selected
    ids=[r.get('sourceId') for r in selected]
    if any(not isinstance(s,str) or not s for s in ids) or len(set(ids))!=len(ids):
        return selected
    anchor=_exact_indexed(selected[0],owner)
    if anchor:
        pool=[r for r in candidates if (identity:=_exact_indexed(r,owner)) and identity[1]==anchor[1]]
        chunks=Counter(r['metadata']['chunk_index'] for r in pool)
        pool=[r for r in pool if chunks[r['metadata']['chunk_index']]==1]
        mode='indexed_scope_condition'
    else:
        first=selected[0];version=first.get('versionId')
        if (not content_hash or not isinstance(version,str) or not version
                or first.get('pdfId')!=owner or first.get('contentHash')!=content_hash
                or first.get('accessLevel')!='fulltext'):
            return selected
        pool=[r for r in candidates if isinstance(r,dict) and r.get('pdfId')==owner and r.get('contentHash')==content_hash
              and r.get('versionId')==version and r.get('accessLevel')=='fulltext'
              and isinstance(r.get('sourceId'),str) and r['sourceId']]
        mode='pdf_scope_condition'
    counts=Counter(r['sourceId'] for r in pool)
    pool=[r for r in pool if counts[r['sourceId']]==1 and condition_score(r)>(0,0,0)]
    if not pool:
        return selected
    ranked=sorted(enumerate(pool),key=lambda pair:(condition_score(pair[1]),-pair[0]),reverse=True)
    detail=ranked[0][1]
    if detail['sourceId'] in ids:
        return selected
    protected={ids[0]}
    for row in selected:
        if row.get('tableData') or row.get('retrievalMode') not in (None,'indexed_hybrid','pdf_lexical_fallback'):
            protected.add(row['sourceId'])
        parent=row.get('contextForSourceId')
        if parent in ids:
            protected.update((row['sourceId'],parent))
    if len(selected)>=limit:
        removable=[i for i,r in enumerate(selected) if r['sourceId'] not in protected]
        if not removable:
            return selected
        selected.pop(removable[-1])
    selected.append({**detail,'retrievalMode':mode})
    return selected
