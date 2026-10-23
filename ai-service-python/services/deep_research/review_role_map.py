"""Declared review tasks and exact links, never source support or approval."""
from collections import Counter
from services.deep_research.review_field_index import field_index

POLICY = '''Judge each actual clause by role, kind AND text/conditions; role labels do not prove truth.
For a genuinely prospective hypothesis, test falsifiability, motivated premises, pairing,
measurement and inference. No prior observed PSNR/SSIM gain is required. Invented observations,
guarantees and unsupported factual premises still fail. Resolve analysisRef/effectBindings into
the actual supplied analysis; formulas/units/aggregation may live in linked analysis or metrics,
not repeated inside hypothesis.effectKeys. Proposed settings need compatible execution, not
proof of author adoption; attributed original method/data/asset claims need OWN E quotations.
Descriptive decisions need bounded interpretation, not an unrequested significance threshold.
Inspect all actual text/conditions/config before alleging absence: present hardware/warmup/
repeats remain present even if their protocol is inadequate. Explain the specific remaining
defect and bind that existing value. Declared links are not dependency or scientific approval.'''

FAILURES = '''For failed verdicts return 1..6 findings using EXACTLY ONE of two object forms:
EXISTING VALUE: keys {kind,claimId,path,reason,value}; kind is incomplete, incompatible or
unsupported. Copy the EXACT COMPLETE existing value at that path, not a paraphrase/substr.
ABSENT FIELD: keys {kind,claimId,path,reason}; kind is missing_field and value is FORBIDDEN.
Only absent text/executionSpec or absent allowed top-level executionSpec keys qualify.
Present/null/empty/invalid fields use EXISTING VALUE, never ABSENT FIELD. Metrics/limits have
no executionSpec; inspect their real text/conditions. Paths use actual keys/zero-based indices.
claimId must be a target or supplied context ID. One precise Chinese defect per finding; cite
the actual unresolved dependency if needed. Passed verdicts require findings:[] AND every
positive audit. Bindings alone never approve/reject science or another target.'''


def build(claims):
    rows=field_index(claims)
    counts=Counter(c.get('claimId') for c in claims if isinstance(c,dict)
        and isinstance(c.get('claimId'),str))
    eligible={r['claimId'] for r in rows}
    by_id={c['claimId']:c for c in claims if isinstance(c,dict)
        and isinstance(c.get('claimId'),str) and c['claimId'] in eligible and counts[c['claimId']]==1}
    metrics=[r['claimId'] for r in rows if r['role']=='metrics']
    for row in rows:
        claim=by_id[row['claimId']];spec=claim.get('executionSpec')
        if row['role']=='hypothesis' and isinstance(spec,dict):
            row['reviewTask']='prediction_and_factual_premises'
            row['purpose']=spec.get('purpose') if isinstance(spec.get('purpose'),str) else None
            ref=spec.get('analysisClaimId')
            row['analysisRef']=ref if isinstance(ref,str) else None
            target=by_id.get(ref) if isinstance(ref,str) else None
            analysis=target.get('executionSpec') if target and target.get('designRole')=='analysis' else None
            effects=analysis.get('effects') if isinstance(analysis,dict) else None
            keys=spec.get('effectKeys')
            row['effectBindings']=([{'claimId':ref,'path':['executionSpec','effects',key]}
                for key in keys if isinstance(key,str) and isinstance(effects,dict) and key in effects]
                if isinstance(keys,list) else [])
            row['analysisResolved']=isinstance(effects,dict)
            row['availableMetricIds']=metrics
        elif row['role']=='analysis' and isinstance(spec,dict):
            decision=spec.get('decision')
            row['decisionMode']=decision.get('mode') if isinstance(decision,dict) else None
            row['availableMetricIds']=metrics
        elif row['role'] in ('metrics','limits'):
            row['reviewTask']='actual_text_and_conditions'
    return rows
