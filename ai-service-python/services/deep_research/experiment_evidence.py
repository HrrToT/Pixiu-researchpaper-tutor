"""Candidates for experimental repairs from actually read, permitted sources.

Candidate permission is not citation or support. The usual fitter, live scope
check, output parser and independent reviewers still apply before publication.
"""
from collections import Counter
from copy import deepcopy
import re
from services.deep_research.contracts import DeepResearchError,digest

_PIN=re.compile(r'(arxiv:(?:\d{4}\.\d{4,5}|[a-z][a-z.-]+/\d{7}))v[1-9]\d*\Z',re.I)
_FIELDS=('sourceId','workId','versionId','contentHash','ownerMaterialId','sourceKind','accessLevel')


def enabled(record):
    return (type(record.get('experimentEvidenceContractVersion')) is int
            and record['experimentEvidenceContractVersion']==1
            and record.get('state',{}).get('outputKind')=='experiment_design')


def _unique(rows,key):
    groups={}
    for row in rows:
        if isinstance(row,dict) and isinstance(row.get(key),str) and row[key]:
            groups.setdefault(row[key],[]).append(row)
    return {identity:values[0] for identity,values in groups.items()
            if len({digest(value) for value in values})==1}


def build_context(record):
    """Freeze minimal source/requirement metadata; never acquire extra text."""
    if not enabled(record):return None
    snapshot=record.get('materialSnapshot') or {}
    versions=_unique(snapshot.get('materialVersions',[]),'id')
    materials=_unique(record.get('materials',[]),'materialId')
    local={}
    for owner in snapshot.get('materialRefs',[]):
        material,version=materials.get(owner),versions.get(owner)
        if (not material or not version or not isinstance(version.get('contentHash'),str)
                or not version['contentHash'] or material.get('contentHash')!=version['contentHash']
                or material.get('versionId')!=version['contentHash']
                or not all(isinstance(material.get(key),str) and material[key] for key in ('workId','versionId'))):
            continue
        local[owner]=(material['workId'],material['versionId'])
    state=record.get('state') or {}
    def view(row):
        return {key:deepcopy(row[key]) for key in (*_FIELDS,'publicationIdentity') if key in row}
    acquired=_unique([view(row) for row in state.get('sources',[])],'sourceId')
    read=_unique([view(row) for row in state.get('readResults',[])],'sourceId')
    sources=[]
    mode=snapshot.get('sourcePolicy',{}).get('mode')
    external=(mode in {'academic_external','external_only'} and record.get('sourcePolicy',{}).get('mode')==mode)
    for sid,row in read.items():
        if (row!=acquired.get(sid) or row.get('accessLevel')!='fulltext'
                or not all(isinstance(row.get(key),str) and row[key] for key in _FIELDS)):
            continue
        owner=row['ownerMaterialId'];pair=(row['workId'],row['versionId'])
        owned=owner in local and pair==local[owner] and row['sourceKind']!='arxiv'
        pin=_PIN.fullmatch(row['versionId'])
        public=(external and row['sourceKind']=='arxiv' and pin and pin[1]==row['workId']==owner)
        if owned or public:sources.append(deepcopy(row))
    requirements=_unique([{key:deepcopy(o[key]) for key in
        ('obligationId','requiredSources','question','completionCriteria') if key in o}
        for item in state.get('plan',[]) for o in item.get('obligations',[])],'obligationId')
    return {'version':1,'sources':sources,'requirements':list(requirements.values())}


def _required_source(source,required):
    pins=[value for value in required if (match:=_PIN.fullmatch(value)) and match[1]==source['workId']]
    if pins:return source['versionId'] in pins
    return bool({source['workId'],source['versionId'],source['ownerMaterialId']} & set(required))


def factor_registry(context):
    """Losslessly group identical requirement mappings, keeping all identities."""
    grouped={}
    for row in context['requirements']:
        mapping=row['requiredSources'];key=digest(mapping)
        if key not in grouped:grouped[key]={'obligationIds':[],'requiredSources':deepcopy(mapping)}
        grouped[key]['obligationIds'].append(row['obligationId'])
    return {**deepcopy(context),'requirements':list(grouped.values())}


def expand(claims,evidence,allowed,context,max_additions=12):
    """Append own permitted candidates; preserve original refs and objects."""
    if (not isinstance(context,dict) or type(context.get('version')) is not int or context['version']!=1
            or not isinstance(context.get('sources'),list) or not isinstance(context.get('requirements'),list)):
        raise DeepResearchError('invalid_experiment_evidence_context','保存的实验候选来源范围无效，尚未发送。')
    sources=_unique(context['sources'],'sourceId')
    requirements=_unique(context['requirements'],'obligationId')
    counts=Counter(row.get('evidenceId') for row in evidence if isinstance(row.get('evidenceId'),str))
    claim_counts=Counter(c.get('claimId') for c in claims if isinstance(c.get('claimId'),str))
    from services.deep_research.experimental_reasoning import DESIGN_ROLES
    from services.deep_research.selection import balanced_sample
    from services.deep_research.synthesis_evidence import order_premises
    result=deepcopy(allowed)
    if type(max_additions) is not int:max_additions=12
    max_additions=max(0,min(24,max_additions))
    for claim in claims:
        cid=claim.get('claimId')
        if (claim_counts[cid]!=1 or cid not in allowed
                or claim.get('kind') not in {'proposal','suggestion','hypothesis'}
                or type(claim.get('designContractVersion')) is not int or claim['designContractVersion']!=2
                or claim.get('designRole') not in DESIGN_ROLES):
            continue
        obligations=claim.get('obligationIds',[])
        if not isinstance(obligations,list):continue
        related=[requirements[oid] for oid in obligations if isinstance(oid,str) and oid in requirements]
        if not related:continue
        required=[]
        for item in related:
            values=item.get('requiredSources',[])
            if not isinstance(values,list) or any(not isinstance(v,str) or not v for v in values):
                raise DeepResearchError('invalid_experiment_evidence_context','冻结的实验来源要求无效，尚未发送。')
            required.extend(values)
        candidates=[]
        for row in evidence:
            sid=row.get('sourceId');source=sources.get(sid) if isinstance(sid,str) else None
            if (not source or counts[row.get('evidenceId')]!=1 or row['evidenceId'] in allowed[cid]
                    or row.get('verification',{}).get('literal')!='passed' or row.get('accessLevel')!='fulltext'
                    or not isinstance(row.get('quote'),str) or not row['quote'].strip()
                    or any(row.get(key)!=source[field] for key,field in (
                        ('sourceWorkId','workId'),('sourceVersionId','versionId'),('contentHash','contentHash')))
                    or row.get('sourcePublicationIdentity')!=source.get('publicationIdentity')):
                continue
            if required:
                if not _required_source(source,required):continue
            elif not set(row.get('obligationIds',[])) & {r['obligationId'] for r in related}:
                continue
            candidates.append(row)
        ordered,_=order_premises(candidates,[{'obligations':related}],limit=len(candidates),membership_intents=True)
        selected=balanced_sample(ordered,lambda row:(row['sourceWorkId'],row['sourceVersionId']),max_additions)
        result[cid].extend(row['evidenceId'] for row in selected)
    return result
