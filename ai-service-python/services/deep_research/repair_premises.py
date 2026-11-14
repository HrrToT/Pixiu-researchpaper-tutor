"""Navigate rejected-draft evidence without granting factual support or access."""
from collections import Counter
from services.deep_research.reading_roles import premise_bundles, quality
from services.deep_research.obligation_binding import eligible_obligation_ids


def required_premises(originals, evidence, allowed, requirements, *, verified_target_ids=()):
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
            candidates=[e for e in evidence if e.get('evidenceId') in allowed.get(cid,[])
                and counts[e.get('evidenceId')]==1 and e.get('verification',{}).get('literal')=='passed'
                and isinstance(e.get('sourceWorkId'),str) and e['sourceWorkId']
                and isinstance(e.get('sourceVersionId'),str) and e['sourceVersionId']
                and eligible_obligation_ids({'workId':e['sourceWorkId'],'versionId':e['sourceVersionId'],
                    'ownerMaterialId':e.get('ownerMaterialId')},own_obligations)]
            chosen,bundles=premise_bundles(candidates,own_obligations,mixed_script_terms=True)
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
        refs=list(dict.fromkeys(e['evidenceId'] for e in chosen))
        preferred.extend(eid for eid in preferred_refs if eid not in preferred)
        audit.append({'claimId':cid,'mode':mode,'originalEvidenceIds':list(old),
            'requiredEvidenceIds':refs,'preferredEvidenceIds':preferred_refs,'navigationBundles':bundles,'verification':'unchecked'})
        for e in chosen:
            if e['evidenceId'] not in seen:selected.append(e['evidenceId']);seen.add(e['evidenceId'])
    return set(selected),{'version':1,'targets':audit,'preferredEvidenceIds':preferred,'verification':'unchecked_navigation'}
