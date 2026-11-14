"""Consistent prospective review and exact declaration links; no approvals."""
from collections import Counter

from services.deep_research.hypothesis_spec import validate_hypothesis_spec
from services.deep_research.execution_spec import execution_spec_errors

DESIGN_POLICY='''Review an executable UNEXECUTED plan, retaining every required role.
Choose concrete intervention levels, budgets and measurement rules now; unknown defaults or
"choose later" fail. Source-attributed operations, exact dataset/version/subset membership,
asserted available counts/native resolutions and released assets need OWN original evidence.
Explicitly proposed hyperparameters/render sizes need compatible implementation, not author
attribution; never relabel an unsupported author fact as a proposal.
Named selection needs quoted membership, not unasserted camera counts or author-used splits.
All/count selection still needs exact capacity. Proposed ordinal/seeded split rules must run
BEFORE fitting, enumerate actual IDs and STOP if either side is empty or overlapping. This
precheck proves no availability/count; actual identity and factual quantities remain checked.
Separate split units from independent analysis units; held-out views differ from held-out scenes.
Final evaluation views must not initialize/train/select checkpoints; early stopping needs a
separate validation set or fixed cap. Specify every seed's role; split/training seeds may differ.
Common states need reproducible acquisition/training, complete compatible states/initial values,
inputs, renderer and optimizer/rates/schedules, with pairing/copying within units. A future hash
is recorded at execution, not required now; a name/hash alone defines no acquisition. A config
reference needs supplied version/file/keys. Train with a finite cap; existing weights need OWN
explicit release/access and locator, not merely authors training weights or releasing code.
FIRST read the requested estimand. Isolated component effects require matched recovery/training
and fixed other conditions; unmatched native pipelines cannot replace that isolated comparison.
WHOLE-stage/pipeline quality/storage/extra-training tradeoffs may instead use finite explicit
unmatched optimization, identical shared preparation/paired observations and honest cost scope.
Do not require an isolated equal-budget primary arm for that different objective; do not claim
isolated parameter causality from it. Audit every actual phase and declared budget cap.
Match hypothesis/analysis and requested inference strength. G1-G0 is an oriented contrast,
not a prediction that G1 improves. Future hypotheses need no observed gain; reject guarantees
or disguised results. Descriptive exploration promises no significance/equivalence/population CI.
Analyze metrics separately; incompatible units cannot be added. Image quality needs held-out
observed references; self-render PSNR can be infinite and invalidate differences. Pair actual
independent units; one scene cannot support a cross-scene bootstrap. Nonsignificance proves
neither equality nor equivalence; equivalence needs declared tolerances and valid uncertainty.
Read linked concrete definitions together without demanding repetition. Declared fields/links
prove neither scientific validity nor accepted dependencies. Preserve initialization, method,
sampling, measurement/reference/aggregation/unit/timing and inference checks. Revisions change
only writable targets; retain concrete accepted choices and report exact conflicting fields.'''

POLICY='''Prospective review contract 3: judge the human objective and actual linked definitions.
Facts need own quotes; proposed choices need compatible executable settings; predictions remain
unconfirmed. Unselected text proves no global absence. Case alone does not change an established
same name; variants stay distinct. Presence index below is computed from declarations only:
present keys cannot be called absent, but can have invalid formulas/units/assumptions. Explain
that actual defect. Never auto-approve a target or its dependency from key presence or syntax.'''


def enabled(version):
    return type(version) is int and version==3


def factorial_reference(version):
    from services.deep_research.design_review_policy import REVIEW_FACTORIAL_REFERENCE
    if not enabled(version):return REVIEW_FACTORIAL_REFERENCE
    return ('Apply these factorial formulas ONLY to an actually requested binary two-factor '
        'comparison; they impose no isolated-effect objective on a whole-stage cost tradeoff.\n'
        + REVIEW_FACTORIAL_REFERENCE.replace('Pair scenes/seeds; match recovery/training budgets; identify independent sampling',
            'Pair scenes/seeds; match recovery/training budgets for isolated effects; identify independent sampling'))


def _proposal(claim):
    return (isinstance(claim,dict) and isinstance(claim.get('claimId'),str) and bool(claim['claimId'].strip())
        and isinstance(claim.get('kind'),str) and claim['kind'] in {'proposal','suggestion','hypothesis'}
        and type(claim.get('designContractVersion')) is int and claim['designContractVersion']==2)


def declaration_links(claims):
    """Exact IDs/keys only; never evaluate formulas or decide inference validity."""
    counts=Counter(c['claimId'] for c in claims if isinstance(c,dict) and isinstance(c.get('claimId'),str))
    by_id={c['claimId']:c for c in claims if _proposal(c) and counts[c['claimId']]==1}
    rows=[]
    for claim in claims:
        if (not _proposal(claim) or counts[claim['claimId']]!=1 or claim.get('designRole')!='hypothesis'
                or type(claim.get('hypothesisContractVersion')) is not int or claim['hypothesisContractVersion']!=1):
            continue
        spec=claim.get('executionSpec');row={'hypothesisId':claim['claimId']}
        try:errors=validate_hypothesis_spec(spec)
        except (TypeError,ValueError,OverflowError):errors=['malformed_hypothesis']
        if errors:
            rows.append({**row,'hypothesisSchemaErrors':errors});continue
        aid=spec['analysisClaimId'];row.update(analysisId=aid,requestedKeys=list(spec['effectKeys']))
        if counts[aid]!=1:
            rows.append({**row,'analysisStatus':'missing_or_ambiguous'});continue
        analysis=by_id.get(aid)
        if not analysis or analysis.get('designRole')!='analysis':
            rows.append({**row,'analysisStatus':'wrong_role_or_contract'});continue
        values=analysis.get('executionSpec')
        try:errors=execution_spec_errors('analysis',values)
        except (TypeError,ValueError,OverflowError):errors=['malformed_analysis']
        if errors:row['analysisSchemaErrors']=errors
        effects=values.get('effects') if isinstance(values,dict) else None
        if not isinstance(effects,dict) or any(not isinstance(key,str) or not key.strip() for key in effects):
            rows.append({**row,'analysisStatus':'invalid_effects_mapping'});continue
        row.update(presentKeys=[k for k in spec['effectKeys'] if k in effects],
            missingKeys=[k for k in spec['effectKeys'] if k not in effects])
        rows.append(row)
    return rows
