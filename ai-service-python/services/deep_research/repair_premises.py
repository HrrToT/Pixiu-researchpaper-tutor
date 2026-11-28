"""Navigate rejected-draft evidence without granting factual support or access."""
import re
from collections import Counter
from copy import deepcopy

from services.deep_research.reading_roles import premise_bundles, quality
from services.deep_research.obligation_binding import eligible_obligation_ids


def comparison_scope(claim, context, evidence):
    """Return a compiled local contribution, not a new research obligation."""
    if context is None:
        return None
    if not isinstance(context, dict) or not isinstance(context.get('layout'), list):
        raise ValueError('Invalid compiled comparison scope')
    cells = [c for c in context['layout'] if claim['claimId'] in c.get('claimIds', [])]
    if not cells:
        return None  # Joint conclusions retain the whole frozen requirement.
    if len(cells) != 1:
        raise ValueError('Ambiguous compiled comparison scope')
    cell = cells[0]
    source = context.get('sources', {}).get(cell.get('source'), {})
    dimension = cell.get('axisTitle', cell.get('question'))
    pair = (source.get('workId'), source.get('versionId'))
    own = [e for e in evidence if e.get('evidenceId') in claim.get('evidenceRefs', [])]
    if (not all(isinstance(v, str) and v for v in (*pair, dimension)) or not own
            or any((e.get('sourceWorkId'), e.get('sourceVersionId')) != pair for e in own)):
        raise ValueError('Comparison scope does not match original sources')
    return {'workId': pair[0], 'versionId': pair[1], 'dimension': dimension}


_OPACITY_DEFINITION = re.compile(r'\bopacity\s*\(?\s*[α𝛼]|\bopacity\s+alpha\b', re.I)


def required_premises(originals, evidence, allowed, requirements, *, verified_target_ids=(), comparison_context=None,
                      local_parameter_definitions=False):
    counts=Counter(e.get('evidenceId') for e in evidence)
    selected=[];seen=set();audit=[];preferred=[]
    for claim in originals:
        cid=claim['claimId'];old=claim.get('evidenceRefs',[])
        own_obligations={o['obligationId']:o for o in requirements
            if o.get('obligationId') in claim.get('obligationIds',[])}
        if cid in verified_target_ids or not own_obligations:
            # Without a frozen target binding, keep the old source protection.
            chosen=[e for e in evidence if e.get('evidenceId') in old and e.get('evidenceId') in allowed.get(cid,[])]
            bundles=[];mode='verified_citations' if cid in verified_target_ids else 'legacy_unbound'
        else:
            scope = comparison_scope(claim, comparison_context, evidence)
            navigation = own_obligations
            if scope is not None:
                # Only navigation is narrowed. Actual frozen goals, permissions,
                # original claims and every available candidate stay unchanged.
                navigation = {oid: {**deepcopy(o), 'question': scope['dimension'],
                    'completionCriteria': [], 'searchQuery': '', 'requestExcerpt': ''}
                    for oid, o in own_obligations.items()}
            candidates=[e for e in evidence if e.get('evidenceId') in allowed.get(cid,[])
                and counts[e.get('evidenceId')]==1 and e.get('verification',{}).get('literal')=='passed'
                and isinstance(e.get('sourceWorkId'),str) and e['sourceWorkId']
                and isinstance(e.get('sourceVersionId'),str) and e['sourceVersionId']
                and eligible_obligation_ids({'workId':e['sourceWorkId'],'versionId':e['sourceVersionId'],
                    'ownerMaterialId':e.get('ownerMaterialId')},own_obligations)]
            chosen,bundles=premise_bundles(candidates,navigation,mixed_script_terms=True,
                **({'processing_cost':True} if comparison_context is not None else {}))
            # Keep each eligible paper/version represented even if the requested
            # role has no lexical match. That absence is not a paper finding.
            pairs=list(dict.fromkeys((e['sourceWorkId'],e['sourceVersionId']) for e in candidates))
            for pair in pairs:
                if any((e['sourceWorkId'],e['sourceVersionId'])==pair for e in chosen):continue
                own=[e for e in candidates if (e['sourceWorkId'],e['sourceVersionId'])==pair]
                head=max(own,key=lambda e:(quality({'text':e.get('quote',''),'location':e.get('location',{}),
                    'tableData':e.get('tableData'),'rankingContext':e.get('sourceContext','')}),
                    e['evidenceId'] in old,-len(e.get('quote',''))))
                chosen.append(head)
            mode='unverified_role_navigation'
        preferred_refs=[e['evidenceId'] for e in chosen]
        if mode=='unverified_role_navigation':
            by_id={e['evidenceId']:e for e in chosen}
            anchors=[];anchored=set()
            for bundle in bundles:
                ids=bundle['evidenceIds'];lead=by_id[ids[-1]]
                pair=(lead['sourceWorkId'],lead['sourceVersionId'])
                if pair not in anchored:
                    anchors.extend(by_id[eid] for eid in ids);anchored.add(pair)
            for e in chosen:
                pair=(e['sourceWorkId'],e['sourceVersionId'])
                if pair not in anchored:anchors.append(e);anchored.add(pair)
            chosen=anchors
            if local_parameter_definitions and scope is not None and re.search(r'不透明度|\bopacity\b',
                    claim.get('text', ''), re.I):
                definitions = [e for e in candidates if e['evidenceId'] in old and e.get('accessLevel') == 'fulltext'
                               and (e['sourceWorkId'], e['sourceVersionId']) == (scope['workId'], scope['versionId'])
                               and _OPACITY_DEFINITION.search(e.get('quote', ''))]
                if definitions and not any(e in chosen for e in definitions):
                    chosen.append(min(definitions, key=lambda e: len(e['quote'])))
        refs=list(dict.fromkeys(e['evidenceId'] for e in chosen))
        preferred.extend(eid for eid in preferred_refs if eid not in preferred)
        audit.append({'claimId':cid,'mode':mode,'originalEvidenceIds':list(old),
            'requiredEvidenceIds':refs,'preferredEvidenceIds':preferred_refs,'navigationBundles':bundles,'verification':'unchecked'})
        for e in chosen:
            if e['evidenceId'] not in seen:selected.append(e['evidenceId']);seen.add(e['evidenceId'])
    return set(selected),{'version':1,'targets':audit,'preferredEvidenceIds':preferred,'verification':'unchecked_navigation'}
