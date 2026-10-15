"""Compact drafting instructions; independent reviewers retain the full policy.

Generation must see the scientific evidence as well as the output contracts.
This guidance does not approve claims, replace structural validation, or change
the full scientific requirements used by verification and repair.
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
Explain split and training seed purposes in prose, not invented schema fields.
Train a baseline with a finite cap or select an evidence-backed existing asset;
copy it within each paired unit and record its resulting identity at execution.
Define initialization by a reproducible operation and its parameters/seed, not
"initialize identically". Give a numeric image size or resizing rule, renderer,
optimizer and actual learning rates/schedule for all trainable parameter groups.
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


def design_drafting_requirements(metric_domains=None, *, compact=False):
    from services.deep_research.metric_scope import metric_protocol_requirements
    protocols = metric_protocol_requirements(metric_domains)
    metrics = '; '.join(f'{domain}: {text}' for domain, text in protocols.items())
    return (_DRAFT_POLICY + '\n' + _DRAFT_STATISTICS + '\n'
            + '\n'.join(f'{role}: {metrics if role == "metrics" else _ROLE_HINTS[role] if compact else requirement}'
                        for role, (_, requirement) in DESIGN_ROLES.items()))


def prospective_draft_prompt(*, question, limit, clarification, gaps, obligations, sources,
                             evidence_marker, claim_fields, claim_limit, section_templates):
    """A proposal gets its own concise request, not a factual-results checklist.

    Full per-role contracts and the independent reviewer are appended elsewhere.
    Source permissions and every explicit user requirement stay visible.
    """
    packed=lambda value:json.dumps(value,ensure_ascii=False,separators=(',',':'))
    return f'''Design an executable, UNEXECUTED experiment answering this complete user request.
Question: {question}
Strict total character limit: {limit or 'concise, no explicit maximum'}
User clarification: {clarification}
Gaps: {packed(gaps)}
Research questions (answer_requirement is mandatory; supporting_research informs it): {packed(obligations)}
Source registry (P keys are not evidenceRefs): {packed(sources)}

Evidence summaries:
{evidence_marker}

Return ONLY compact JSON with sections: [{{title,claimIds}}], claims: [{{{claim_fields}}}].
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
