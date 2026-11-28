"""Keep owned processing-work passages in mixed cost/metric retrieval.

Selection is a hint, not a relevance or scientific verdict. No additional
retrieval, embedding, PDF read or model request is made here.
"""
from collections import Counter
import hashlib
import re

_ASK=re.compile(r'\b(?:costs?|overheads?|processing time|training time|training steps?)\b|成本|开销|处理时间|训练时间|训练步数',re.I)
_NEGATIVE=re.compile(r'(?:不要|不用|无需|不必|忽略|\b(?:ignore|exclude|without)\b)[^，,。.;；\n]{0,12}(?:costs?|overheads?|成本|开销)',re.I)
_PROCESS=re.compile(r'\b(?:train\w*|fine[ -]?tun\w*|optimi\w*|distill\w*|recover\w*|prun\w*|preprocess\w*|compress\w*|quantiz\w*)\b|训练|微调|优化|蒸馏|恢复|剪枝|预处理|压缩|量化',re.I)
_WORK=re.compile(r'\b(?:iterations?|steps?|epochs?|seconds?|minutes?|hours?|milliseconds?|runtime|FLOPs?)\b|迭代|步数|训练时间|处理时间|计算开销',re.I)
_AMOUNT=re.compile(r'\b\d[\d,.]*[kKmM]?\s*(?:iterations?|steps?|epochs?|seconds?|minutes?|hours?|milliseconds?|FLOPs?)\b|\d+\s*(?:次迭代|步|秒|分钟|小时)',re.I)
_OWN=re.compile(r'\b(?:we|our)\b|我们|本文',re.I)
_EXCLUDED=re.compile(r'related work|background|references|bibliography|\btable\b|相关工作|参考文献',re.I)
_SCOPE=re.compile(r'\b(?:conditions?|limitations?|scope|ablat\w*|sensitiv\w*)\b|条件|边界|局限|消融|敏感',re.I)


def requested(text):
    return bool(isinstance(text,str) and _ASK.search(text) and not _NEGATIVE.search(text))


def enabled(record):
    from services.deep_research.comparison_review_batches import current_profile
    from services.deep_research.request_context import effective_question
    return current_profile(record) and requested(effective_question(record))


def obligation_requested(obligation):
    return requested(' '.join(str(obligation.get(key,'')) for key in
                              ('question','searchQuery','requestExcerpt')))


def score(row):
    body=re.split(r'\bContent:\s*',row.get('text',''),maxsplit=1)[-1]
    section=(row.get('metadata') or {}).get('section_title') or (row.get('location') or {}).get('section','')
    if (_EXCLUDED.search(str(section)) or body.lstrip().startswith('Table caption:')
            or not _OWN.search(body) or not _PROCESS.search(body) or not _WORK.search(body)):
        return 0
    return 4*bool(_AMOUNT.search(body))+2*bool(re.search(r'implementation|experimental settings|training details|实现|设置',str(section),re.I))+1


def codebook_training_score(text, section):
    if _EXCLUDED.search(section):
        return 0
    text = ' '.join(text.split())
    return 5 * bool(re.search(
        r'\b(?:fine[ -]?tun\w*|optimi[sz]\w*|train\w*)[^.!?]{0,55}\bcodebook\b[^.!?]{0,90}'
        r'\b\d[\d,]*\s*(?:iterations?|steps?|epochs?|seconds?|minutes?|hours?)\b', text, re.I))


def recovery_training_score(text, section):
    if _EXCLUDED.search(section):
        return 0
    text = ' '.join(text.split())
    amount = _AMOUNT.pattern
    operation = r'\b(?:co[ -]?adaptation|pruning recovery)\b'
    return 5 * bool(re.search(rf'{operation}[^.!?]{{0,120}}(?:{amount})'
                              rf'|(?:{amount})[^.!?]{{0,120}}{operation}', text, re.I))


def _pdf_exact(row,owner,content_hash):
    if (not isinstance(row,dict) or not isinstance(content_hash,str) or not content_hash
            or row.get('pdfId')!=owner or row.get('contentHash')!=content_hash
            or row.get('accessLevel')!='fulltext' or row.get('metadata')):
        return False
    location=row.get('location') or {}
    if (set(location)!={'page','offset'} or type(location['page']) is not int or location['page']<1
            or type(location['offset']) is not int or location['offset']<0):return False
    expected=hashlib.sha256(f'{owner}:{content_hash}:{location}'.encode()).hexdigest()
    return row.get('sourceId')=='src_'+expected


def include_processing_cost(rows,candidates,record,query,owner,limit):
    from services.deep_research.comparison_review_batches import current_profile
    from services.deep_research.request_context import effective_question
    from services.deep_research.source_continuity import _exact_indexed,needs_preceding_context
    selected=list(rows[:max(0,limit)])
    if (not current_profile(record) or limit<2 or not selected or not requested(query)
            or not requested(effective_question(record))):return selected
    if not any(m.get('materialId')==owner for m in record.get('materials',[])):return selected
    ids=[r.get('sourceId') for r in selected]
    if any(not isinstance(v,str) or not v for v in ids) or len(set(ids))!=len(ids):return selected
    anchor=_exact_indexed(selected[0],owner)
    if anchor:
        pool=[r for r in candidates if (info:=_exact_indexed(r,owner)) and info[1]==anchor[1]]
    else:
        material=next((m for m in record.get('materials',[]) if m.get('materialId')==owner),{})
        digest=material.get('contentHash')
        if not _pdf_exact(selected[0],owner,digest):return selected
        pool=[r for r in candidates if _pdf_exact(r,owner,digest)]
    counts=Counter(r['sourceId'] for r in pool)
    pool=[r for r in pool if counts[r['sourceId']]==1]
    ranked=sorted((r for r in pool if score(r)),key=lambda r:(-score(r),r['sourceId']))
    if ranked and ranked[0]['sourceId'] in ids:return selected
    protected={ids[0]}
    # Prefer explicitly requested rows over an incidental later table. Keep
    # their already-selected section context, including unparsed captions.
    anchors=[r for r in selected if r.get('retrievalMode')=='indexed_requested_row']
    table=next((r for r in selected if r.get('tableData') or (r.get('metadata') or {}).get('table_id')),None)
    if table:anchors.append(table)
    for row in anchors:
        protected.add(row['sourceId'])
        info=_exact_indexed(row,owner)
        if info:
            protected.update(r['sourceId'] for r in selected
                             if (other:=_exact_indexed(r,owner)) and other[1:]==info[1:])
    for row in selected:
        mode=row.get('retrievalMode')
        # Generic task-level ablation hints must not crowd out explicitly
        # requested processing work. Query-specific conditions remain pinned.
        generic_scope=mode in {'indexed_scope_condition','pdf_scope_condition'} and not _SCOPE.search(query)
        if mode not in (None,'indexed_hybrid','pdf_lexical_fallback') and not generic_scope:
            protected.add(row['sourceId'])
        if row.get('contextForSourceId'):
            protected.update((row['sourceId'],row['contextForSourceId']))
    for detail in ranked:
        if detail['sourceId'] in ids:continue
        additions=[{**detail,'retrievalMode':'indexed_processing_cost' if anchor else 'pdf_processing_cost'}]
        if needs_preceding_context(detail):
            if not anchor:continue
            chunk,version,section=_exact_indexed(detail,owner)
            previous=[r for r in pool if _exact_indexed(r,owner)==(chunk-1,version,section)]
            if len(previous)!=1:continue
            if previous[0]['sourceId'] not in ids:
                additions.insert(0,{**previous[0],'retrievalMode':'indexed_preceding_context',
                                    'contextForSourceId':detail['sourceId']})
        needed=max(0,len(selected)+len(additions)-limit)
        removable=[i for i,r in enumerate(selected) if r['sourceId'] not in protected]
        removable.sort(key=lambda i:(selected[i].get('retrievalMode') in {'indexed_scope_condition','pdf_scope_condition'},-i))
        if needed>len(removable):continue
        for index in sorted(removable[:needed],reverse=True):selected.pop(index)
        selected[1:1]=additions
        return selected
    return selected
