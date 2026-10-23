"""Owned, actually read procedural dependencies for experiment drafting.

This selects literal inputs, never operations, scientific values or verdicts.
"""
import re
import hashlib

from services.deep_research.method_intent import operation_score
from services.deep_research.reading_priority import _method_bundle
from services.deep_research.source_continuity import method_reference
from services.deep_research.quote_context import _sentence_cuts


def _read_text(source):
    if not isinstance(source,dict) or not isinstance(source.get('pages',[]),list):return None
    values=[source.get('text'),*[p.get('text') for p in source.get('pages',[]) if isinstance(p,dict)]]
    values=list(dict.fromkeys(v for v in values if isinstance(v,str) and v.strip()))
    return values[0] if len(values)==1 else None


def _owned(source,work):
    if not isinstance(source,dict) or not isinstance(source.get('location'),dict):return False
    sid=source.get('sourceId','');location=source.get('location') or {}
    match=re.fullmatch(re.escape(work)+r'-v[0-9a-f]{16}-chunk-(\d+)',str(sid))
    return bool(match and source.get('workId')==source.get('ownerMaterialId')==work
        and source.get('accessLevel')=='fulltext' and _read_text(source)
        and type(location.get('chunk')) is int and location['chunk']==int(match[1])
        and isinstance(location.get('section'),str) and location['section'].strip()
        and all(isinstance(source.get(k),str) and source[k].strip() for k in ('versionId','contentHash'))
        and hashlib.sha256(_read_text(source).encode('utf8')).hexdigest()==source['contentHash'])


def requested_operation(view):
    return (any(isinstance(c,dict) and c.get('responseType')=='procedure' for c in view.get('completionCriteria',[]))
        or bool(re.search(r'设计.{0,12}实验|实验(?:操作|步骤)|初始化|执行步骤|'
            r'\b(?:experiment(?:al)? (?:design|plan)|design[^.!?]{0,30}experiment|initialization|execution steps)\b',
            view.get('question',''),re.I)))


def _evidence_for(source,rows,oid):
    text=_read_text(source);eligible=[]
    for row in rows:
        if (not isinstance(row,dict) or not isinstance(row.get('location'),dict)
                or not isinstance(row.get('verification'),dict)):continue
        quote=row.get('quote','')
        if (row.get('verification',{}).get('literal')!='passed' or row.get('accessLevel')!='fulltext'
                or row.get('tableData') or row.get('location',{}).get('table')
                or oid not in row.get('obligationIds',[]) or not isinstance(quote,str) or not quote.strip()
                or row.get('sourceContext')!=text or text.count(quote)!=1
                or row.get('location',{}).get('section')!=source['location']['section']
                or any(row.get(a)!=source.get(b) for a,b in (('sourceId','sourceId'),
                    ('sourceWorkId','workId'),('sourceVersionId','versionId'),('contentHash','contentHash')))):
            continue
        # Prefer an actual numeric rule over a qualitative motivation from the
        # same read passage. Earliest occurrence breaks ties, not a new fact.
        numeric=bool(re.search(r'\d\.\d|\d\s*%|[=＝∼~]\s*[\[({]?\s*[-+]?\d',quote))
        eligible.append((numeric,-text.index(quote),row))
    return max(eligible,key=lambda item:item[:2])[2] if eligible else None


def _following_context(source,row):
    text=_read_text(source);end=text.index(row['quote'])+len(row['quote'])
    suffix=text[end:];cuts=_sentence_cuts(suffix)
    stop=cuts[min(2,len(cuts)-1)] if cuts else len(suffix)
    # At most three whole sentences from an already bounded read. A long
    # sentence must reach the fitter and become an explicit capacity gap.
    # Never silently drop its context or clip an equation to fit a budget.
    return {'before':'','after':suffix[:stop],'truncated':bool(text.index(row['quote']) or stop<len(suffix))}


def operational_bundle(rows,read_sources,oid,work):
    """Choose one complete, at-most-three-source method chain for this owner.

    Every quote/context is checked against a unique actual read identity. Missing
    or ambiguous identities cannot be borrowed from another source. The caller
    must keep the complete bundle or report a capacity gap.
    """
    if not isinstance(work,str) or not work:return [],{}
    readable=[s for s in read_sources if _owned(s,work)]
    readable=[s for s in readable if sum(r.get('sourceId')==s['sourceId'] for r in readable)==1]
    choices=[]
    for anchor in readable:
        if not method_reference({'text':_read_text(anchor)}):continue
        previous=_method_bundle({**anchor,'text':_read_text(anchor)},
            [{**s,'text':_read_text(s)} for s in readable],set())
        if not previous:continue
        chain=[*previous,anchor];bundle=[];contexts={}
        for source in chain:
            row=_evidence_for(source,rows,oid)
            if row is None:break
            context=_following_context(source,row)
            bundle.append(row)
            if context['after'].strip():contexts[row['evidenceId']]=context
        if len(bundle)!=len(chain):continue
        score=sum(operation_score(_read_text(source),source['location']['section'],'operation',operational=True)
            for source in chain)
        if score<=0:continue
        choices.append((score,len(chain),bundle,contexts))
    if not choices:return [],{}
    chosen=max(choices,key=lambda item:item[:2])
    return chosen[2],chosen[3]
