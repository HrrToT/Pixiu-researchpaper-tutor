"""Preserve explicit arXiv revisions without changing the literal question."""
from copy import deepcopy
import re

from services.deep_research_academic import checked_arxiv_id

_IDENTITY = r'(?:\d{4}\.\d{4,5}|[a-z][a-z.-]+/\d{7})v[1-9]\d*'
_REFERENCE = re.compile(
    r'(?<![A-Za-z0-9_./])(?:arxiv\s*:\s*|https?://(?:www\.)?arxiv\.org/(?:abs|pdf|html)/)?'
    r'(?P<identity>'+_IDENTITY+r')(?:\.pdf)?(?![A-Za-z0-9_./])', re.I)


def enabled(record):
    return type(record.get('exactDiscoveryContractVersion')) is int and record['exactDiscoveryContractVersion']==2


def work_id(identity):
    return re.sub(r'v\d+$','',identity)


def explicit_revisions(question):
    result={}
    for match in _REFERENCE.finditer(question):
        revision='arxiv:'+checked_arxiv_id(match['identity'].lower())
        values=result.setdefault(work_id(revision),[])
        if revision not in values:values.append(revision)
    return result


def validate_constraints(constraints):
    if not isinstance(constraints,dict):
        raise ValueError('Invalid requested source revisions')
    for work,revisions in constraints.items():
        if (not isinstance(work,str) or not work.startswith('arxiv:') or work_id(work)!=work
                or not isinstance(revisions,list) or not revisions):
            raise ValueError('Invalid requested source revisions')
        checked_arxiv_id(work[6:])
        for revision in revisions:
            if not isinstance(revision,str) or work_id(revision)!=work or revision==work:
                raise ValueError('Invalid requested source revisions')
            checked_arxiv_id(revision[6:])


def bind(identities, question, *, default=False):
    """Literal revision constraints override model-chosen latest/other revisions.

    Multiple explicitly requested revisions of one work stay distinct. A model
    may bind a particular requested revision; an unversioned work needs all of
    its requested revisions, never an arbitrary latest choice.
    """
    pins=explicit_revisions(question);result=[]
    for value in identities:
        if not isinstance(value,str) or not value.lower().startswith('arxiv:'):
            continue
        try:identity='arxiv:'+checked_arxiv_id(value.split(':',1)[1].lower())
        except ValueError:continue
        revisions=pins.get(work_id(identity),[])
        if len(revisions)==1:
            resolved=revisions
        elif revisions and identity not in revisions:
            if identity!=work_id(identity):
                raise ValueError('Requested arXiv revisions conflict with the generated source')
            resolved=revisions
        else:
            resolved=[identity]
        result.extend(x for x in resolved if x not in result)
    if not result and default:
        result=[v for values in pins.values() for v in values]
    return result


def normalize_plan(plan, question, allowed, required_default):
    """Work/version references remain visible in the durable plan and audit."""
    normalized=deepcopy(plan);changes=[]
    for item in normalized:
        for obligation in item['obligations']:
            before=deepcopy(obligation.get('requiredSources',[]))
            local=[value for value in before if value in allowed]
            external=bind(before,question,default=not local and not allowed)
            after=list(dict.fromkeys([*local,*external])) or list(required_default)
            obligation['requiredSources']=after
            if before!=after:
                changes.append({'obligationId':obligation['obligationId'],
                                'before':before,'after':deepcopy(after)})
    covered={value for item in normalized for o in item['obligations'] for value in o['requiredSources']}
    # Local selected materials use their own content identities; their publication
    # revision is not inferred from a human citation. Never relabel a local PDF.
    if not allowed and any(value not in covered for revisions in explicit_revisions(question).values() for value in revisions):
        raise ValueError('An explicitly requested arXiv revision is missing from the generated plan')
    return normalized,{'requestedRevisions':explicit_revisions(question),'changes':changes}
