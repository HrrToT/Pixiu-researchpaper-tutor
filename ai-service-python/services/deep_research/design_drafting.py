"""Compact drafting instructions; independent reviewers retain the full policy.

Generation must see the scientific evidence as well as the output contracts.
This guidance does not approve claims, replace structural validation, or change
the full scientific requirements used by independent verification. Repair
generation may use this same guidance; its output is independently checked.
"""
from services.deep_research.experimental_reasoning import DESIGN_ROLES
import json


_DRAFT_POLICY = """
Propose an executable, unexecuted experiment answering the actual user question.
Choose concrete settings now, labeled as proposals; never attribute chosen values
to the paper. Dataset/subset membership, available counts and existing assets
remain factual and require the supplied fulltext. Named scenes use the exact
quoted labels and capitalization; ground those names, not an unasserted original
view count or author split. Do not substitute a parent dataset for a cited subset.
Split held-out views within each reconstruction scene, with reproducible rules
and nonempty train/evaluation checks. Without actual file IDs, choose a proposed
every_nth or seeded_fraction rule; "official training/test views" are not file IDs.
Split before fitting. Final evaluation views cannot choose checkpoints; use separate
validation for early stopping or choose a fixed training cap.
Explain split and training seed purposes in prose, not invented schema fields.
Train a baseline with a finite cap or select an evidence-backed existing asset;
copy it within each paired unit and record its resulting identity at execution.
Define initialization by a reproducible operation and its parameters/seed, not
"initialize identically". Give a numeric image size or resizing rule, renderer,
optimizer and actual learning rates/schedule for all trainable parameter groups.
Create EVERY new state from explicitly available inputs or explicit fresh values:
the baseline cannot supply an enhancement that has not yet been created. State
tensor/primitive selection and transformations, not just "copy" or an RNG seed.
Name the actual rendering/evaluation operation or implementation; a general
framework or device name alone is not an executable rendering configuration.
"Read defaults later" is not a choice: cite an actually supplied version/config/key
or choose labeled proposed values now. Unknown defaults are not paper evidence.
Disable other interventions in both groups or give their shared executable policy.
For isolated effects match whole-group training budgets; freezing a parameter
does not mean zero group training. Baseline acquisition is shared preparation,
followed by the per-group budget in recovery, not an extra invented third phase.
Keep all roles consistent. A simple descriptive comparison needs paired estimates
and bounded conclusions, not invented independent views, bootstrap or significance.
Respect the requested factors/scenes and metric domains; add no unnecessary tests.
Unknown source facts are bounded gaps, not proof that the paper omitted them.
For typed roles, text adds rationale/conditions, not a second copy of the fields;
the application already renders their full settings. Use only the documented schema.
"""

_DRAFT_STATISTICS = """
Statistical reference (only for two binary factors): groups 00,10,01,11.
Define loss L by negating higher-is-better metrics; keep lower-is-better metrics.
Use finite measurements against the same held-out observed reference; comparing
baseline renders with themselves gives infinite PSNR. Analyze metrics separately.
A at B=0/1: L10-L00 / L11-L01; B at A=0/1: L01-L00 / L11-L10.
Average main effects are the averages of those pairs. Interaction
I=L11-L10-L01+L00 tests additivity; telescoping sums do not test it.
Pair scenes/seeds. Views or seeds of one scene are not independent scene samples.
One scene supports descriptive effects, not cross-scene bootstrap inference.
Zero-effect testing needs compatible uncertainty; non-significance is not
equivalence/independence. Equivalence needs a declared metric tolerance and an
interval contained inside it. Distinguish zero-recovery diagnostics from a full
pipeline. Never claim an unexecuted result or add incompatible metric units.
"""


_ROLE_HINTS = {
    'hypothesis':'State a prospective estimand, linked to the actual analysis purpose; no promised significance.',
    'groups':'Use the requested factors/scenes, explicit operations/levels and application order.',
    'controls':'Define shared initialization and all matching settings using actual operation parameters.',
    'data':'Ground exact dataset/subset membership; choose a reproducible split and seed purpose, with prechecks.',
    'budget':'Give finite baseline acquisition and consistent per-group recovery amounts.',
    'steps':'Order acquisition, initialization, paired copies, interventions, optimization, rendering and artifact records.',
    'analysis':'Define separate metric effects, actual pairing/aggregation units, compatible uncertainty and decisions.',
    'limits':'Bound confounding and generalization; distinguish what a controlled within-unit contrast can identify from population claims.'}


_TARGETED_BASE = '''Draft only the writable roles; accepted definitions are fixed and sibling drafts are
unverified consistency context. Use complete typed configurations and concrete proposed values now,
not unknown defaults or later choices. Proposed values are unexecuted choices, not author settings.
Existing dataset/subset membership, available counts, paper operations and released assets require
own supplied fulltext. Never infer paper-wide absence. Retain the user's actual objective, scope,
finite budgets and necessary controls. Renderer suffixes will expose fields; prose must agree and
need not repeat them. Independent review retains the full scientific and operational policy.'''
_TARGETED_ROLE = {
    'data':'Ground the exact dataset/subset and scene names. Choose executable within-scene view splits with seeds, nonempty checks and split-before-fit; final evaluation cannot select checkpoints. Identify the analysis unit rather than declaring nearby views independent.',
    'groups':'Specify the requested factors, exact control/treatment operations and all necessary numeric levels. Parameter groups and binary IDs must agree with controls, budgets, states and hypothesis; unsupported source facts cannot become proposed choices.',
    'controls':'Define actual common initialization, state/parameter identities, renderer, numeric image sizing, optimizer/rates/schedule, other interventions and seeds. Use only available inputs/fresh states; cite a supplied version/config/key or choose explicit values, never unknown defaults.',
    'budget':'Choose finite shared baseline acquisition/training and matched per-group optimization amounts for an isolated effect; keep stopping rules, units and IDs consistent. Existing assets require release/access evidence; otherwise propose bounded fresh training.',
    'steps':'Order split, acquisition, explicit state creation, paired copies, interventions, optimization and matched rendering/evaluation. Record actual artifacts/hashes at execution; filenames alone do not define how initialization is obtained. No unavailable upstream state.',
    'hypothesis':'State one bounded prospective hypothesis linked to the actual analysis ID/effect keys. Explore/descriptive does not require or promise statistical rejection/equivalence; purpose and statement must agree with the chosen decision method.',
    'analysis':'Define each actual paired metric effect, view/time aggregation, seed handling and compatible uncertainty/decision. Descriptive paired estimates need no significance test. Inferential resampling needs actual independent units; one scene does not support cross-scene confidence. Mixed metric directions are a tradeoff.',
    'metrics':'Define executable observations, references, units and directions for each requested metric; distinguish reconstruction quality from reference-free stability and teacher distortion. Never combine incompatible units or use infinite self-PSNR in arithmetic.',
    'limits':'Bound inference to the selected scene/settings and measured observables. State confounding, unavailable references and generalization limits without claiming authors omitted tests. A caveat cannot rescue a design incapable of identifying the requested effect.'}


def design_drafting_requirements(metric_domains=None, *, compact=False, roles=None,
                                 targeted=False,factorial_reference=True,concise_policy=False):
    from services.deep_research.metric_scope import metric_protocol_requirements
    protocols = metric_protocol_requirements(metric_domains)
    metrics = '; '.join(f'{domain}: {text}' for domain, text in protocols.items())
    statistics = _DRAFT_STATISTICS if factorial_reference and (roles is None or set(roles) & {'hypothesis', 'analysis'}) else ''
    if concise_policy:
        return (_TARGETED_BASE+'\n'+statistics+'\n'+'\n'.join(
            role+': '+(metrics if role=='metrics' else _ROLE_HINTS[role])
            for role in DESIGN_ROLES if roles is None or role in roles))
    if targeted:
        return (_TARGETED_BASE+'\n'+statistics+'\n'+'\n'.join(
            role+': '+_TARGETED_ROLE[role]+(' '+metrics if role=='metrics' else '')
            for role in DESIGN_ROLES if roles is None or role in roles))
    return (_DRAFT_POLICY + '\n' + statistics + '\n'
            + '\n'.join(f'{role}: {metrics if role == "metrics" else _ROLE_HINTS[role] if compact else requirement}'
                        for role, (_, requirement) in DESIGN_ROLES.items() if roles is None or role in roles))


def prospective_draft_prompt(*, question, limit, clarification, gaps, obligations, sources,
                             evidence_marker, claim_fields, claim_limit, section_templates,concise=False):
    """A proposal gets its own concise request, not a factual-results checklist.

    Full per-role contracts and the independent reviewer are appended elsewhere.
    Source permissions and every explicit user requirement stay visible.
    """
    packed=lambda value:json.dumps(value,ensure_ascii=False,separators=(',',':'))
    if concise:
        return f'''Design an executable, UNEXECUTED experiment for this complete user request.
Question: {question}
Total text/conditions character limit: {limit or 'concise; no explicit maximum'}
User clarification: {clarification}
Gaps: {packed(gaps)}
Frozen research requirements (goals, never source evidence): {packed(obligations)}
Source registry (paper identity metadata, not scientific evidence): {packed(sources)}
Evidence summaries:
{evidence_marker}
Return ONLY {{"sections":[],"claims":[]}}. Sections use title/claimIds. Each claim uses {claim_fields}.
Section titles: {packed(section_templates)}. Maximum {claim_limit} claims, including EVERY required
designRole with its complete typed configuration. Explicit requested paper facts need separately
supported reported/inference claims; proposed choices need no author attribution. Existing dataset/
subset membership, method operations, counts and released assets require EACH claim's OWN supplied
E citations. Empirical table values require exact visible tableBindings; never relabel a fact as a
proposal or invent missing evidence, results or novelty. Abstract facts stay abstract-level.
Write concise Chinese rationale/conditions once; typed settings are rendered by the app. Keep every
role mutually consistent, including initialization, data split, budgets, measurements and decisions.
Do not publish E/P IDs or raw hashes. Preserve the requested scope and name any specific evidence gap.'''
    return f'''Design an executable, UNEXECUTED experiment answering this complete user request.
Question: {question}
Strict total character limit: {limit or 'concise, no explicit maximum'}
User clarification: {clarification}
Gaps: {packed(gaps)}
Research questions (answer_requirement is mandatory; supporting_research informs it): {packed(obligations)}
Source registry (P keys are not evidenceRefs): {packed(sources)}

Evidence summaries:
{evidence_marker}

Return ONLY one JSON OBJECT: {{"sections":[],"claims":[]}}. Fill both arrays.
Each section uses title/claimIds; each claim uses {claim_fields}.
Do not combine section rows and claim rows in one array.
Use these section titles: {packed(section_templates)}. At most {claim_limit} claims;
include each required designRole and its complete typed configuration. Explicitly requested
original facts/measurements still require separate supported reported/inference claims.
Proposed numeric choices need no quotation saying the authors used them. Existing dataset
membership, method facts and assets require each claim's OWN supplied E references.
Paper measurements need exact tableBindings [{{evidenceId,rowNumber,groupIndex,metric,value}}]
from visible tableData, retaining dataset/method/variant/metric/units. Never relabel a fact
as a proposal to bypass evidence; absent passages do not prove paper-wide absence.
Use only supplied E references; no E/P IDs or raw hashes in published text or conditions.
Write concise Chinese. Text supplies rationale and necessary conditions, not a second copy
of typed settings. Keep all roles mutually consistent; no hidden extra optimization phase.
Meet the actual requested scope, not a retelling of every original benchmark. Do not invent
data, released assets, original settings, results or novelty. Distinguish facts, inference,
hypothesis and unexecuted choices. If required support is unavailable, keep the specific gap.'''


def synthesis_obligations(plan):
    """Keep frozen user deliverables; research subtasks inform, not redefine them.

    Supporting questions and source permissions remain visible. Their research
    checklist is audited by the unchanged plan elsewhere, rather than repeated
    here as a demand to reproduce every original paper setting in a proposal.
    """
    result = []
    for item in plan:
        for obligation in item.get('obligations', []):
            keys = ('obligationId', 'question', 'purpose', 'requiredSources')
            if obligation.get('purpose') != 'supporting_research':
                keys += ('requestExcerpt', 'completionCriteria')
            result.append({key: obligation[key] for key in keys if key in obligation})
    return result
