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
