"""Allocate missing design deliverables for one bounded, independently checked repair."""
from copy import deepcopy
from collections import Counter

from services.deep_research.experimental_reasoning import DESIGN_ROLES


def prepare_design_completion(report, verification, evidence, plan):
    """Keep original drafts/verdicts intact; register empty slots as rejected only.

    Slots authorize prose generation, not publication or new facts. The existing
    repair whitelist, immutable kinds/roles and independent verifier still apply.
    """
    draft, checked = deepcopy(report), deepcopy(verification)
    obligations = list(dict.fromkeys(o['obligationId'] for item in plan
        for o in item.get('obligations', [])
        if isinstance(o.get('obligationId'), str) and o['obligationId']))
    counts = Counter(e.get('evidenceId') for e in evidence if isinstance(e.get('evidenceId'), str))
    refs = [e['evidenceId'] for e in evidence
            if isinstance(e.get('evidenceId'), str) and e['evidenceId']
            and counts[e['evidenceId']] == 1
            and e.get('verification', {}).get('literal') == 'passed'
            and e.get('accessLevel') == 'fulltext'
            and e.get('sourceWorkId') and e.get('sourceVersionId')
            and set(e.get('obligationIds', [])) & set(obligations)]
    if not refs:
        return draft, checked
    claims = draft.setdefault('claims', [])
    existing_roles = {c.get('designRole') for c in claims
                      if c.get('kind') in {'proposal', 'suggestion', 'hypothesis'}
                      and isinstance(c.get('designRole'), str)}
    ids = {c.get('claimId') for c in claims}
    ids.update(c.get('claimId') for c in checked.get('accepted', []))
    ids.update(c.get('claimId') for c in checked.get('rejected', []))
    for role, (_, requirement) in DESIGN_ROLES.items():
        if role in existing_roles:
            continue
        identity = 'design_completion_' + role
        while identity in ids:
            identity += '_new'
        ids.add(identity)
        claims.append({'claimId': identity, 'kind': 'hypothesis' if role == 'hypothesis' else 'proposal',
                       'designRole': role, 'designContractVersion': 2, 'text': '',
                       'evidenceRefs': list(refs), 'obligationIds': list(obligations),
                       'detailLevel': 'fulltext'})
        if role == 'budget' and type(draft.get('budgetContractVersion')) is int and draft['budgetContractVersion'] == 1:
            claims[-1]['budgetContractVersion'] = 1
        if role == 'hypothesis' and type(draft.get('hypothesisContractVersion')) is int and draft['hypothesisContractVersion'] == 1:
            claims[-1]['hypothesisContractVersion'] = 1
        if role in {'controls','data'} and type(draft.get('protocolContractVersion')) is int and draft['protocolContractVersion']==1:
            claims[-1]['protocolContractVersion']=1
        from services.deep_research.experiment_workflow import workflow_version
        if role == 'steps' and workflow_version(draft.get('workflowContractVersion')):
            claims[-1]['workflowContractVersion'] = draft['workflowContractVersion']
        checked.setdefault('rejected', []).append({'claimId': identity,
            'reason': 'missing_design_deliverable', 'detail': requirement})
    return draft, checked
