"""Reuse literal extraction, not a new goal's relevance or scientific verdict."""
from services.deep_research.contracts import digest


def enabled(record):
    return (type(record.get('sourcePassageReuseContractVersion')) is int
        and (record['sourcePassageReuseContractVersion'] in (1,2) or rejected_state_enabled(record))
        and type(record.get('adaptiveExtractionContractVersion')) is int
        and record['adaptiveExtractionContractVersion']==3)


def failure_reuse_enabled(record):
    return enabled(record) and record['sourcePassageReuseContractVersion'] in (2,3)


def rejected_state_enabled(record):
    """A new journal binds literal rejection and its glyph audit immutably."""
    return (type(record.get('sourcePassageReuseContractVersion')) is int
        and record['sourcePassageReuseContractVersion']==3
        and type(record.get('sourceGlyphContractVersion')) is int and record['sourceGlyphContractVersion']==1
        and type(record.get('adaptiveExtractionContractVersion')) is int and record['adaptiveExtractionContractVersion']==3)


def key(frozen):
    return digest({k:v for k,v in frozen.items() if k!='obligations'})


def register(index, entry):
    identity=key(entry['input'])
    if identity not in index:index[identity]=entry
    elif index[identity] is not None and any(index[identity][k]!=entry[k]
                                            for k in ('evidenceId','evidenceDigest')):
        index[identity]=None  # Ambiguous locations/projections must be resolved again.


def same_metadata(old, source, quote, start, offset):
    from services.deep_research.table_evidence import visible_table_packet
    expected={'sourceKind':source.get('sourceKind','local'),'sourceTitle':source.get('title',''),
        'sourceUrl':source.get('url',''),'sourceQuoteStart':start,'sourceContextStart':offset,
        'extractionKind':'source_passage','ownerMaterialId':source.get('ownerMaterialId') or None,
        'sourcePublicationIdentity':source.get('publicationIdentity') or None,
        'tableData':visible_table_packet(source.get('tableData'),quote)}
    return all(old.get(k)==v for k,v in expected.items())
