"""Source-column identity for a table's plain author-owned `Ours` row.

Display context only: never substitutes for a cell, source quote or semantic
verdict. Baselines and marked/ablation variants keep their literal identities.
"""


def for_record(record):
    from services.deep_research.comparison_intent import operations_enabled
    if not operations_enabled(record):
        return None
    draft=record.get('state',{}).get('comparisonCellDraft')
    if not isinstance(draft,dict) or type(draft.get('layoutVersion')) is not int or draft['layoutVersion']!=3:
        return None
    from services.deep_research.comparison_presentation import metadata
    try:
        return metadata(draft)
    except (KeyError,TypeError,ValueError):
        return None


def author_headers(claim,evidence,presentation):
    """Resolve exactly one rendered source column, with full citation ownership."""
    if (not isinstance(presentation,dict) or type(presentation.get('version')) is not int
            or presentation['version']!=3 or not isinstance(presentation.get('layout'),list)
            or not isinstance(presentation.get('sources'),dict)):
        return {}
    cid=claim.get('claimId')
    slots=[row for row in presentation['layout'] if isinstance(row,dict)
           and isinstance(row.get('claimIds'),list) and cid in row['claimIds']]
    if (not isinstance(cid,str) or not cid or len(slots)!=1
            or slots[0]['claimIds'].count(cid)!=1
            or claim.get('obligationIds')!=[slots[0].get('obligationId')]):
        return {}
    alias=slots[0].get('source')
    if not isinstance(alias,str):return {}
    source=presentation['sources'].get(alias)
    if not isinstance(source,dict):return {}
    work,version,title=(source.get(k) for k in ('workId','versionId','title'))
    if any(not isinstance(v,str) or not v.strip() for v in (work,version,title)):
        return {}
    refs=claim.get('evidenceRefs');by_id={}
    for e in evidence:
        if not isinstance(e,dict) or not isinstance(e.get('evidenceId'),str):return {}
        if e['evidenceId'] in by_id:return {}
        by_id[e['evidenceId']]=e
    if (not isinstance(refs,list) or not refs or any(not isinstance(ref,str) for ref in refs)
            or len(refs)!=len(set(refs))):
        return {}
    if any(ref not in by_id or by_id[ref].get('sourceWorkId')!=work
           or by_id[ref].get('sourceVersionId')!=version
           or not isinstance(by_id[ref].get('verification'),dict)
           or by_id[ref]['verification'].get('literal')!='passed' for ref in refs):
        return {}
    # The title is the actual rendered column label. No method alias is guessed
    # from a title prefix, paper name, acronym, number or model-generated field.
    return {ref:title for ref in refs}
