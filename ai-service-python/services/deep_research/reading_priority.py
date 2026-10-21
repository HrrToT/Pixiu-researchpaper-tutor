"""Bounded obligation/paper reading order before model extraction."""
import re
from services.deep_research.extraction_priority import prioritize_extraction_passages
from services.deep_research.source_continuity import needs_preceding_context,method_reference
from services.deep_research.obligation_binding import eligible_obligation_ids


def select_read_sources(sources, obligations, limit, *, extracted=(),priority_version=6,illustrative_context=False,method_context=False):
    """Retain owned source identities and exact predecessor bundles.

    Storage ID order is not relevance order. Rank retrieved text by each
    obligation/paper, then read unextracted candidates first under the same cap.
    A predecessor is eligible only from the same work, version, index family
    and section; neither its text nor its source permissions are merged.
    """
    readable=[]
    for source in sources:
        namespace=re.fullmatch(r'(.+)-v[0-9a-f]{16}-chunk-\d+',source['sourceId'])
        if namespace and namespace[1]!=source.get('workId'):
            continue  # An indexed ID cannot claim another paper's work identity.
        if eligible_obligation_ids(source,obligations):
            readable.append(source)
    pending=[(s,s.get('location',{}),s.get('text','')) for s in readable]
    ordered=[row[0] for row in prioritize_extraction_passages(pending,obligations,priority_version)]
    ordered.sort(key=lambda s:(s['sourceId'],s.get('contentHash')) in extracted)
    selected=[];used=set()
    for source in ordered:
        if source['sourceId'] in used:
            continue
        bundle=[]
        identity=re.fullmatch(r'(.+-v[0-9a-f]{16}-chunk-)(\d+)',source['sourceId'])
        if method_context is True:
            bundle=_method_bundle(source,readable,used)
        elif identity and int(identity[2])>0 and needs_preceding_context(source,illustrative=illustrative_context):
            prior_id=identity[1]+str(int(identity[2])-1)
            predecessors=[s for s in readable if s['sourceId']==prior_id
                and s.get('workId')==source.get('workId') and s.get('versionId')==source.get('versionId')
                and s.get('ownerMaterialId')==source.get('ownerMaterialId')
                and s.get('location',{}).get('section')==source.get('location',{}).get('section')
                and isinstance(source.get('location',{}).get('section'),str)
                and source['location']['section'].strip()]
            if illustrative_context is True:
                predecessors=[s for s in predecessors
                    if source.get('accessLevel') == s.get('accessLevel') == 'fulltext'
                    and type(source.get('location',{}).get('chunk')) is int
                    and source['location']['chunk'] == int(identity[2])
                    and type(s.get('location',{}).get('chunk')) is int
                    and s['location']['chunk'] == int(identity[2])-1]
            if len(predecessors)==1 and prior_id not in used:
                bundle.append(predecessors[0])
        bundle.append(source)
        if len(selected)+len(bundle)>limit:
            continue
        selected.extend(bundle);used.update(s['sourceId'] for s in bundle)
    return selected


def _method_bundle(source,readable,used):
    chain=[];current=source
    for _ in range(2 if method_reference(source) else 1):
        identity=re.fullmatch(r'(.+-v[0-9a-f]{16}-chunk-)(\d+)',str(current.get('sourceId','')))
        section=current.get('location',{}).get('section')
        if (not identity or int(identity[2])<1 or not isinstance(section,str) or not section.strip()
                or current.get('accessLevel')!='fulltext' or type(current.get('location',{}).get('chunk')) is not int
                or not isinstance(current.get('ownerMaterialId'),str) or not current['ownerMaterialId'].strip()
                or not isinstance(current.get('versionId'),str) or not current['versionId'].strip()
                or current['location']['chunk']!=int(identity[2])
                or not needs_preceding_context(current,illustrative=True,procedural=True)):
            break
        pid=identity[1]+str(int(identity[2])-1)
        matches=[r for r in readable if r['sourceId']==pid and r.get('accessLevel')=='fulltext'
            and r.get('workId')==current.get('workId') and r.get('versionId')==current.get('versionId')
            and r.get('ownerMaterialId')==current.get('ownerMaterialId')
            and r.get('location',{}).get('section')==section
            and type(r.get('location',{}).get('chunk')) is int and r['location']['chunk']==int(identity[2])-1]
        if len(matches)!=1 or pid in used:break
        chain.append(matches[0]);current=matches[0]
    return list(reversed(chain))
