"""One prospective review instruction set, with complete original inputs.

Only new server-versioned runs use this view. It does not transform claims,
source packets, configuration values, audit validators or verdicts.
"""
import json


def enabled(version, review_version, claims):
    return (type(version) is int and version in (1,2,3,4,5,6,7,8,9)
            and type(review_version) is int and review_version == 3
            and bool(claims) and all(c.get('kind') in {'proposal','suggestion','hypothesis'}
                and type(c.get('designContractVersion')) is int and c['designContractVersion'] == 2
                for c in claims))


COMMON = '''Judge the complete human objective as an executable UNEXECUTED design. Choose actual
levels/budgets/measurement rules now; unknown defaults or "choose later" fail. Facts need the
target's OWN original E evidence, not another claim, metadata or model plan. Resolve subjects
with surrounding sentences; check EVERY clause/condition, number's method/dataset/metric/unit/
setting and actual inference. Abstract facts stay abstract-level; table facts need exact bindings;
an ablation is not a general/main-table result. Reject invented results, exclusive/universal scope
and paper-wide absence inferred from missing selected text. Never relabel a source fact as a choice.
Proposed values need compatible executable settings, not authors' values or observed improvement.
Dataset/version/subset membership, asserted original counts/resolution and released assets remain
facts. Named selection needs scene membership, not unasserted camera counts/IDs or authors' split.
All/count selection needs actual capacity. Ordinal/seeded splits enumerate actual IDs BEFORE fit
and STOP if empty/overlapping; these checks establish no factual availability. Split units differ
from independent analysis units; holding out views differs from holding out whole scenes.
Final evaluation cannot initialize/train/tune/select. Validation is training-only or use a fixed
cap. Specify every seed's purpose; split/training seeds need not match. Shared states need full
compatible initialization/acquisition, inputs, renderer, optimizer/rates/schedules and paired copies.
Actual config references identify a supplied version/file/key; unknown defaults or future names/
hashes do not define acquisition. Record resulting hashes at execution, not invent them now.
Training needs finite caps; existing weights need own explicit release/access, not just code or
authors training a model. Isolated effects require matched whole-group optimization/conditions;
whole-stage quality/storage/extra-training tradeoffs may use finite explicit unmatched cost with
identical shared preparation/paired observations and honest scope, not isolated parameter causality.
Read linked concrete definitions together; no needless repetition or automatic dependency approval.
Preserve methods, initialization, measurement/reference/aggregation/unit/timing and inference checks.
Metrics have separate units/directions; quality needs observed held-out references, not infinite
self-PSNR differences. Pair actual independent units; one scene supports no cross-scene bootstrap.
Non-significance proves no equality/equivalence; tolerances and compatible uncertainty are needed.
Only targets receive verdicts. Context is not approved evidence. Revisions retain concrete accepted
choices, not silence as a gap restriction. Explain exact conflicting path/value/constraint; present
fields can be incomplete/invalid, but cannot be called absent.'''

PROTOCOL = '''Protocol2: controls.initialization.workflowClaimId resolves the ONLY initialization in that
exact Workflow4 definition; the paired_initialization audit may bind this pointer only when its
complete definition fulfills the slot. No competing source/initialization. Data prechecks reject
duplicate/missing IDs and empty/overlapping splits. seeded_fraction sorts IDs, shuffles with its
seed, takes min(N-1,max(1,floor(N*f))) evaluation items for N>=2. These choices assert no author count.'''

DERIVED = '''Derived configuration meanings below are calculations, NOT evidence/approval. Sums use
same-unit baseline plus ONE declared whole-group recovery cap; never infer frame multipliers,
asset-zero cost or coverage of omitted phases. Check per-frame/window scope and original prose.
Equal arithmetic alone cannot fail; identify an incompatible field/phase/value. No extra total
field forbidden by schema is required. Presence/links are declarations, not verified dependencies.'''

WORKFLOW = '''Steps bind exact data/budget/controls/groups IDs. Check acquisition, split-before-fit,
actual creation inputs, paired copies, seed rebuilding/warm starts, checkpoint selection,
training/rendering/optimization and artifact records in temporal order. Evaluation cannot
initialize/train/tune/select; validation is training-only, fixed_budget selects the last capped
step. A base model contains no uncreated enhancement. Workflow4: enumerate EVERY required
representation/network state; check name/dtype/count/shape/initial value, input axes, broadcast,
normalization/units and creation/render/update compatibility. A seed/scalar/opaque vector,
framework name or valid schema is not a model/renderer. Deriving needs actual selectors and
transformations; fresh creation needs compatible explicit values/distributions. No competing
checkpoints, omitted phases or fabricated assets; fixed starts are not independent training.
Original prose must agree.'''

BUDGET = '''Budget1 owns finite shared preparation/per-group recovery. Compare ALL prose/definitions
to exact values/units. Binary IDs follow factor order (0 control,1 treatment). Cover EVERY
fitting phase, per-frame/window scope; no reused cap hiding phases. Isolated effects match
whole-group training; whole-stage tradeoffs allow finite explicit unmatched cost, honestly
attributed. Sums prove no phase coverage. Baseline needs a maximum or own released-asset evidence.
Zero recovery is an explicit bounded diagnostic, not hidden training.'''

HYPOTHESIS = '''Hypothesis1 links a prospective statement to ONE analysis ID and exact effect keys.
Read prose AND typed statement against the linked definitions: explore requires descriptive
uncertainty/decision and promises no statistical rejection/equivalence; test_zero requires a valid
interval-based zero-effect decision; assess_equivalence requires positive metric tolerances and
valid uncertainty. An oriented G1-G0 contrast predicts no gain. Non-significance/near equality
proves neither additivity, equivalence nor independence. Matching IDs/keys is not approval.'''

AUDIT = '''Return ONLY a JSON array: one {claimId,status:passed|failed,reason,designAudit} per target.
Pass needs EVERY slot. Use ONE form per slot:
{claimId,quote}:exact nonblank substring; {quotes:[{claimId,quote}]}:1..32 exact segments,
punctuation unchanged; {ref:{claimId,path}}:unchanged existing typed value;
{fields:[{claimId,path,value}]}:1..32 exact typed values; {claimId,path,value}:one fields entry.
Paths:object keys/zero-based indices under allowed executionSpec roots, not serialized JSON.
Source role/contracts apply: controls need supported protocol, budget Budget1,
step fields supported workflow. per_group_steps binds recovery, never baseline alone.
Bind target/context proposals, NEVER source facts as configuration. Together bindings cover the
ENTIRE slot, not keywords/promises. Missing/vague choices stay null and fail; use slot keys,
not roles/arrays. Data/assets also need source-bound availability audits, not measured results.
Fill the exact skeleton; no extra targets.'''

DATA = '''For data targets, existing dataset/version/subset membership is factual; proposed split/window,
seeds and prechecks are choices. An inherited subset is NOT its parent. A passed data target needs
dataAvailability={evidenceId:OWN fulltext E ID,quote:exact substring of its quote,
scopeQuote:exact words IN that same passage identifying this dataset/subset,
availableNames:[exact selected source labels],availableCount:integer,countQuote:exact count token}.
Named mode needs selected-name membership in that SAME own passage, not original camera IDs,
unasserted counts, native resolution or the authors' split; count fields may be omitted. Proposed
ordinal/seeded rules enumerate actual IDs before fitting and STOP if empty/overlapping. These
checks establish no actual count/availability. Asserted original quantities still need evidence.
For ASCII case-only label differences of the SAME established identity, add nameBindings:
[{selectedName:requested spelling,sourceLabel:exact availableNames spelling}]. No synonyms,
path/URL normalization, fuzzy or version matching. Preserve literal case in the quoted audit.
sorted_first needs the actual available unit count and exact decimal or English one..twenty
count token; requested count cannot exceed it. all needs exact entire-subset capacity; an
unambiguously complete dataset needs no invented names/order. Never use a view/method count
as scene count. Missing source support or unresolved subset fails. Literal-name candidates only
locate own quotes; they are NOT membership proof. Never mix one row's ID with another's words.'''

ASSET = '''Existing-baseline targets need assetAvailability={evidenceId:OWN fulltext E ID,
quote:exact substring of that evidence quote,assetQuote:exact selected checkpoint identity
WITHIN availabilityQuote,availabilityQuote:exact explicit release/access clause,
locator:published https:// locator appearing in quote}. The SAME released asset must match
selection, method, scene and version. Authors training a model does not release its weights.
Code-only/future/on-request releases or guessed locators fail; unrelated code/training clauses
cannot be combined into weights availability. Propose finite baseline training when needed,
never invent an asset. This audits source text, not a tested download.'''


def build(*,claims_text,context,question,evidence_marker,metric_domains,config_mode,version=1):
    from services.deep_research import review_instructions as brief
    compact=type(version) is int and version in (6,7,8,9)
    from services.deep_research.review_alignment import factorial_reference,declaration_links
    from services.deep_research.experimental_reasoning import DESIGN_ROLES
    from services.deep_research.design_audit import design_slots_for_claim,audit_field_roots
    from services.deep_research.asset_availability import requires_existing_asset
    from services.deep_research.configuration_consistency import facts
    from services.deep_research.metric_scope import metric_protocol_requirements
    from services.deep_research.synthesis import SCIENTIFIC_TERMINOLOGY
    packed=lambda value:json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    claims=json.loads(claims_text);all_claims=[*claims,*context];roles={c.get('designRole') for c in claims}
    parts=['Independently verify an UNEXECUTED experimental design.',
        'Review mode: '+('operational configuration' if config_mode else 'scientific validity'),
        brief.COMMON if compact else COMMON,SCIENTIFIC_TERMINOLOGY,
        'Original research question (objective, not evidence):\n'+packed(question),
        'Claims:\n'+claims_text,
        'Other proposed statements, for consistency only (not evidence and not verdict targets):\n'+packed(context),
        'Evidence:\n'+evidence_marker]
    if any(c.get('protocolContractVersion')==2 for c in all_claims):parts.append(brief.PROTOCOL if compact else PROTOCOL)
    if any(c.get('workflowContractVersion') in (1,2,3,4) for c in all_claims):parts.append(brief.WORKFLOW if compact else WORKFLOW)
    if any(c.get('budgetContractVersion')==1 for c in all_claims):parts.append(brief.BUDGET if compact else BUDGET)
    if any(c.get('hypothesisContractVersion')==1 for c in all_claims):parts.append(brief.HYPOTHESIS if compact else HYPOTHESIS)
    # Do not impose a factorial reference on an explicitly single-toggle task.
    # Missing/contradictory factors retain the reference rather than guessing.
    from services.deep_research.experiment_envelope import two_arm_request
    groups=[c for c in all_claims if c.get('designRole')=='groups']
    single=(two_arm_request(question) and bool(groups) and all(
        isinstance(c.get('executionSpec'),dict) and isinstance(c['executionSpec'].get('factors'),list)
        and len(c['executionSpec']['factors'])==1 for c in groups))
    if not config_mode and not single:parts.append(factorial_reference(3))
    requirements={role:DESIGN_ROLES[role][1] for role in DESIGN_ROLES if role in roles}
    if 'budget' in roles:requirements['budget']='Fulfill the complete Budget1 rule above, with all actual phases, units and group caps.'
    if 'metrics' in roles:requirements['metrics']=metric_protocol_requirements(metric_domains)
    parts.append('Entire target-role requirements:\n'+packed(requirements))
    slots={c['designRole']:value for c in claims if c.get('designRole')
        and (value:=design_slots_for_claim(c,metric_domains)) is not None}
    if slots:
        roots=audit_field_roots(dict.fromkeys(s for row in slots.values() for s in row),
            workflow_v4=any(c.get('workflowContractVersion')==4 for c in all_claims))
        audit=brief.AUDIT if compact else AUDIT
        if version in (3,4,5,6,7,8,9):
            audit=audit.replace('Return ONLY a JSON array: one',
                'Return ONLY {"items":[...]}: exactly one')
        parts += [audit,'Allowed slot roots (under executionSpec, source role required):\n'+packed(roots)]
    else:
        parts.append('Return ONLY {"items":[...]}: exactly one {claimId,status:passed|failed,reason,designAudit:{}} per target.'
            if version in (3,4,5,6,7,8,9) else 'Return ONLY a JSON array, one {claimId,status:passed|failed,reason,designAudit:{}} per target.')
    data=any(c.get('designRole')=='data' for c in claims)
    asset=any(requires_existing_asset(c) for c in claims)
    if data:parts.append(DATA)
    if asset:parts.append(ASSET)
    skeleton=[{'claimId':c['claimId'],'status':'failed','reason':'',
        **({'findings':[]} if type(version) is int and version in (5,6,7,8,9) else {}),
        'designAudit':{slot:None for slot in slots.get(c.get('designRole'),())},
        **({'dataAvailability':None} if c.get('designRole')=='data' else {}),
        **({'assetAvailability':None} if requires_existing_asset(c) else {})} for c in claims]
    if version in (3,4,5,6,7,8,9):
        parts.append('Exact response skeleton (fill EVERY target, including failures; even one target stays inside items):\n'
            +packed({'items':skeleton}))
    else:parts.append('Exact per-target response skeleton:\n'+packed(skeleton))
    derived=facts(all_claims)
    if derived:parts += [brief.DERIVED if compact else DERIVED,'Derived configuration meanings (not evidence):\n'+packed(derived)]
    links=declaration_links(all_claims)
    if links and version not in (7,8,9):parts.append('Declared key presence (not scientific approval):\n'+packed(links))
    if type(version) is int and version in (2,3,4,5,6,7,8,9):
        parts.append(brief.REJECTED if compact else 'Rejected context policy: reviewContextState is a server rejection record, NOT approval. '
            'Read the exact supplied text/configuration and checks to distinguish an absent field from an '
            'invalid or rejected definition. Context is never a verdict target or factual evidence. '
            'Do not assume its acquisition, source membership, state or measurement is valid; name the '
            'actual incompatible/missing field. A target depending on an unresolved definition is not '
            'an executable approved experiment. Only independent checks and dependency gates may approve it.')
    if type(version) is int and version in (4,5,6,7,8,9):
        from services.deep_research.experiment_execution_guidance import data_declarations,REVIEW
        if version in (7,8,9):
            from services.deep_research.review_field_index import field_index,POLICY,PROSPECTIVE_POLICY
            if version==9:
                from services.deep_research.review_role_map import build as role_map,POLICY as ROLE_POLICY
                parts += [ROLE_POLICY,'Actual review fields (not evidence or approval):\n'+packed(role_map(all_claims))]
            else:parts += [PROSPECTIVE_POLICY if version==8 else POLICY,'Actual review fields (not evidence or approval):\n'+packed(field_index(all_claims))]
        else:
            parts += [brief.DECLARATIONS if compact else REVIEW,'Exact data declarations (not evidence or approval):\n'+packed(data_declarations(all_claims))]
    if type(version) is int and version in (5,6,7,8,9):
        from services.deep_research.rejection_audit import POLICY
        if version==9:
            from services.deep_research.review_role_map import FAILURES
            parts.append(FAILURES)
        else:parts.append(brief.FAILURES if compact else POLICY)
    return '\n\n'.join(parts)
