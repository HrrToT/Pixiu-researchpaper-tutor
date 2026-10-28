"""Offline QA seed for factual verification, never an application import API.

Keep generation context needed by repair while discarding prior verification,
revision and publication state. Private drafting intent is not scientific proof.
"""
from copy import deepcopy


GENERATION_KEYS=('plan','metricDomains','outputKind','assumptions','constraints','title',
    'sources','evidence','readResults','reportVersionId','synthesisContainer',
    'synthesisPremiseAllocation','factualDraftingAudit','synthesisPresentationAudit',
    'synthesisScopeExpressionAudit')


def seed_verification_state(state):
    report=state.get('reportBody')
    if not isinstance(report,dict) or not isinstance(report.get('claims'),list):
        raise ValueError('Saved generation report is required')
    claims=report['claims']
    ids=[c.get('claimId') for c in claims if isinstance(c,dict)]
    if (len(ids)!=len(claims) or any(not isinstance(k,str) or not k.strip() for k in ids)
            or len(set(ids))!=len(ids)):
        raise ValueError('Saved generation claim identities must be unique')
    result={k:deepcopy(state[k]) for k in GENERATION_KEYS if k in state}
    result['reportBody']={'sections':deepcopy(report.get('sections',[])),
        'claims':[{k:deepcopy(v) for k,v in c.items() if k!='verification'} for c in claims]}
    return result
