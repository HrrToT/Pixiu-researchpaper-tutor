"""Shared statistical reference for drafting and reviewing prospective experiments.

This is guidance, not a proof that arbitrary model prose is mathematically valid.
It applies to any binary two-factor experiment, independently of paper content.
"""

FACTORIAL_REFERENCE = """
For a two-factor binary experiment, label groups 00, 10, 01, 11 explicitly.
Define each metric's loss L first: negate a higher-is-better metric, retain a
lower-is-better metric. Never subtract raw metrics with opposite directions as
though the same sign meant quality loss. Analyze metrics separately; do not
add PSNR, SSIM and LPIPS or average their incompatible units.
Conditional effects: A at B=0 is L10-L00, A at B=1 is L11-L01;
B at A=0 is L01-L00, B at A=1 is L11-L10.
Average main effects are [(L10-L00)+(L11-L01)]/2 for A and
[(L01-L00)+(L11-L10)]/2 for B. These are identifiable from these FOUR groups;
additional intervention levels are needed to generalize beyond these levels,
not to compute these averages.
Interaction is I=L11-L10-L01+L00. The testable additivity hypothesis is I=0.
L11-L00=(L10-L00)+(L11-L10) is always a telescoping identity and is NOT a
test of additivity or independence. Independence is not established by an
approximately equal point estimate or a non-significant interaction.
For practical equivalence, predeclare a metric-specific tolerance and assess
an uncertainty interval relative to it; otherwise report the estimate and
uncertainty without claiming no interaction. Use paired scenes/seeds, identify
the independent sampling unit, and keep recovery/training budgets matched.
An intervention without recovery is a valid diagnostic only if explicitly
distinguished from an end-to-end compression procedure with recovery.
"""

# Each role is a separately checked deliverable, not a keyword-based verdict.
DESIGN_ROLES = {
    'hypothesis': ('假设', 'State the testable prospective hypothesis and its limited estimand.'),
    'groups': ('分组表', 'Specify every intervention group, factor levels and how each is constructed; distinguish truncation, distillation and the full pipeline.'),
    'controls': ('固定条件', 'Fix paired baseline checkpoints, rendering settings and all other interventions, including quantization when relevant.'),
    'data': ('固定条件', 'Give a closed scene list or deterministic selection rule, an executable train/evaluation split rule, actual paired seed values or their generation rule, and the independent sampling unit. Saying "fixed split/same seed/multiple scenes" is incomplete. Label proposed choices, never attribute them to the paper.'),
    'budget': ('固定条件', 'Specify recovery/optimization steps and matched budgets for every group. Explicit zero recovery is valid for a diagnostic; separate native-budget results from matched-budget results.'),
    'steps': ('执行步骤', 'Give executable ordered steps and saved artifacts: checkpoint identity, split, seed, intervention configuration, recovery budget, renders and raw measurements.'),
    'metrics': ('指标', 'Specify quality direction and image/view aggregation protocol; speed device/resolution, warmup, synchronization, timed region and repetitions; storage files/representation and units. A list of PSNR/SSIM/LPIPS/FPS/MB without a measurement protocol is incomplete. Never combine incompatible units.'),
    'analysis': ('结果解释', 'Specify estimable effects, uncertainty calculation and confidence level, and a concrete decision rule. Separate rejection of I=0 from practical equivalence: an interval including zero cannot reject I=0; containment within a declared tolerance is needed for equivalence. If no tolerance is chosen, report uncertainty without an equivalence claim. Never claim independence or an unexecuted result.'),
    'limits': ('风险', 'State confounders, invalidation conditions and limits of the proposed intervention, including what this experiment cannot establish.'),
}
DESIGN_ROLE_LABELS = {'hypothesis': '待验证假设', 'groups': '实验分组', 'controls': '固定条件',
                     'data': '数据划分与重复试验', 'budget': '训练与恢复预算', 'steps': '执行步骤与记录',
                     'metrics': '指标与测量口径', 'analysis': '结果判断方法', 'limits': '风险与适用边界'}


def design_requirements():
    return '\n'.join(f'{role}: {requirement}' for role, (_, requirement) in DESIGN_ROLES.items())


def missing_design_roles(claims):
    covered = {c.get('designRole') for c in claims
               if c.get('verification') == 'proposal'
               and isinstance(c.get('designRole'), str)
               and c.get('kind') in {'proposal', 'suggestion', 'hypothesis'}}
    return [role for role in DESIGN_ROLES if role not in covered]
