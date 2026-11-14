"""Describe available answer fields; never repair or approve audit bindings."""
from collections import Counter


def build(claims, metadata, *, allow_access=True):
    if type(allow_access) is not bool:raise ValueError("Invalid access binding policy")
    counts = Counter(c.get('claimId') for c in claims if isinstance(c.get('claimId'), str))
    records = metadata.get('sourceAccessRecords', {})
    records=records if isinstance(records,dict) else {}
    rows = []
    for claim in claims:
        identity = claim.get('claimId')
        if not isinstance(identity, str) or counts[identity] != 1:
            continue
        fields = []
        if isinstance(claim.get('text'), str) and claim['text'].strip():
            fields.append('text')
        if isinstance(claim.get('conditions'), dict) and claim['conditions']:
            fields.append('conditions')
        refs = claim.get('evidenceRefs', [])
        if (allow_access and metadata.get('sourceAccessSummary') and type(metadata.get('taskSourceAccessContractVersion')) is int and metadata['taskSourceAccessContractVersion'] == 1
                and refs and all(records.get(ref) in {'fulltext', 'abstract', 'user_note'} for ref in refs)):
            fields.append('sourceAccessSummary')
        rows.append({'claimId': identity, 'fields': fields})
    return rows


GUIDANCE = '''Answer binding catalog lists the ONLY available fields for each claim.
Choose the minimum real fields that support each check, not every catalog entry.
An absent or empty conditions object is not a field you may bind. Do not invent
conditions bindings to indicate that no extra conditions were requested.
sourceAccessSummary answers only an explicit access-disclosure command, never
scientific content. For a mixed original request bind actual scientific text plus
the server label when each is needed. Scientific criteria still require prose.
Do not claim covered merely because a field exists. Partial/missing checks must
identify actual missing content. Invalid fields remain invalid; do not repair them.'''


def build_scoped(claims,metadata,requirements,permissions):
    """Describe check-specific existing permissions, never grant new ones."""
    from services.deep_research.joint_answer_bindings import access_instruction
    result=[]
    for requirement in requirements:
        permitted=permissions.get(requirement['obligationId'],{})
        checks=[]
        for check in requirement['checks']:
            cid=check.get('criterionId')
            allow=(cid in permitted.get('criteria',set()) if cid is not None else
                   bool(permitted.get('overall')) and bool(access_instruction(check['requirement'],citation_access=True)))
            checks.append({'checkId':check['checkId'],'claims':build(claims,metadata,allow_access=allow)})
        result.append({'obligationId':requirement['obligationId'],'checks':checks})
    import json
    catalogs=[];indices={};obligations=[]
    for obligation in result:
        checks=[]
        for check in obligation['checks']:
            signature=json.dumps(check['claims'],ensure_ascii=False,separators=(',',':'))
            if signature not in indices:
                indices[signature]=len(catalogs);catalogs.append(check['claims'])
            checks.append({'checkId':check['checkId'],'catalogIndex':indices[signature]})
        obligations.append({'obligationId':obligation['obligationId'],'checks':checks})
    wire={'catalogs':catalogs,'obligations':obligations}
    if expand_scoped(wire)!=result:raise ValueError('Scoped catalog round trip failed')
    return wire


def expand_scoped(wire):
    from copy import deepcopy
    if not isinstance(wire,dict) or set(wire)!={'catalogs','obligations'}:
        raise ValueError('Invalid scoped catalog packet')
    catalogs=wire['catalogs'];obligations=wire['obligations']
    if not isinstance(catalogs,list) or not isinstance(obligations,list):raise ValueError('Invalid scoped catalog rows')
    result=[];seen=set()
    for obligation in obligations:
        if (not isinstance(obligation,dict) or set(obligation)!={'obligationId','checks'}
                or not isinstance(obligation['obligationId'],str) or not obligation['obligationId']
                or obligation['obligationId'] in seen or not isinstance(obligation['checks'],list)):
            raise ValueError('Invalid scoped obligation')
        seen.add(obligation['obligationId']);checks=[];check_ids=set()
        for check in obligation['checks']:
            if (not isinstance(check,dict) or set(check)!={'checkId','catalogIndex'}
                    or not isinstance(check['checkId'],str) or not check['checkId'] or check['checkId'] in check_ids
                    or type(check['catalogIndex']) is not int or not 0<=check['catalogIndex']<len(catalogs)):
                raise ValueError('Invalid scoped catalog reference')
            check_ids.add(check['checkId'])
            rows=catalogs[check['catalogIndex']]
            if not isinstance(rows,list):raise ValueError('Invalid scoped field catalog')
            checks.append({'checkId':check['checkId'],'claims':deepcopy(rows)})
        result.append({'obligationId':obligation['obligationId'],'checks':checks})
    return result


SCOPED_GUIDANCE='Each fixed check selects catalogs[catalogIndex], where catalogIndex is zero-based. Restore that exact claim/field list for the matching obligationId/checkId. Sharing a list does not share scope permissions or scientific support. A displayed label may exist without answering the check. Output ordinary claimId/field bindings, never catalogIndex.'
