"""Concise review wording; all experimental constraints remain in force."""

REVIEW_DESIGN_POLICY = '''Review an executable, UNEXECUTED prospective plan.
Choose actual intervention levels, budgets and measurement rules now; "choose later"
fails. Proposed choices need no paper attribution. Existing dataset/subset identity,
membership/capacity, counts, resolutions and released assets require source evidence.
Named selection needs exact scene membership, not unasserted total counts or author
splits. An unambiguous complete dataset/subset permits all mode without a name list;
unresolved identity/capacity fails. Splits need executable rules or actual item IDs,
not labels/unknown official defaults; precheck both sides nonempty. Randomness with
a fixed seed is reproducible. Specify each seed's purpose and selection procedure;
training/split seeds need not match. Distinguish split units from independent analysis
units: scene reconstruction holds out views within scenes; holding out whole scenes
is a different generalization task. Shared definitions may be referenced across roles.
Split before any fitting. Final evaluation views must not train or choose checkpoints;
early stopping needs separate validation or a fixed training cap.
Shared checkpoints need reproducible acquisition/training, parameters, seeds and
within-unit group copying, then artifact identity/hash recorded at execution. A future
hash need not exist now; filenames or recording hashes alone do not define acquisition.
Specify actual initialization, optimizer/rates/schedule and numeric resolution/resize
rules. "Same settings" or unknown defaults fail. An executable config reference names
the supplied version, file and relevant keys; otherwise choose concrete values now.
New baseline training needs a finite budget or stopping rule WITH a maximum. Existing
weights need explicit release/access evidence for the selected asset and selection
rule. Authors having trained a model, a code URL or "ask if available" is insufficient.
Without asset evidence, choose finite reproducible baseline training now and align
controls, seed pairing and steps; never silently substitute an unknown author asset.
Align hypothesis and analysis: descriptive exploration cannot promise a statistical
test, acceptance or equivalence. Match the user's estimand: isolating intervention
effects requires matched recovery/optimization and other conditions; explicit zero
recovery is a bounded diagnostic. Unmatched native pipelines may supplement, not
replace this primary comparison; a confounding warning is insufficient. Preserve a
user's different whole-pipeline/resource-budget objective when actually requested.
Revisions retain concrete accepted choices, not gaps implied by silence. Fill missing
details only in allowed targets without changing/contradicting accepted statements.
'''

REVIEW_FACTORIAL_REFERENCE = '''For binary two-factor designs, define groups 00/10/01/11.
Define loss L per metric: negate higher-is-better, retain lower-is-better. Analyze
metrics separately; never add/average incompatible PSNR/SSIM/LPIPS units or assign
one quality-loss sign to opposite metric directions. Arithmetic requires finite
losses against the SAME reference. Image quality uses held-out observed images.
Teacher/baseline-render distortion is a different estimand: self-comparison PSNR is
infinite, making PSNR factorial differences undefined; use finite error or observed GT.
Conditional A effects: L10-L00 (B=0), L11-L01 (B=1); B: L01-L00 (A=0), L11-L10 (A=1).
Average A=[(L10-L00)+(L11-L01)]/2; B=[(L01-L00)+(L11-L10)]/2. FOUR groups identify
these averages; extra levels are needed for generalization, not their calculation.
Interaction I=L11-L10-L01+L00; additivity tests I=0. Telescoping
L11-L00=(L10-L00)+(L11-L10) is always an identity, never a test of additivity or
independence. Near equality/non-significance proves neither. Practical equivalence
requires a predeclared metric tolerance and an uncertainty interval relative to it;
otherwise report estimates/uncertainty without claiming no interaction.
Pair scenes/seeds; match recovery/training budgets; identify independent sampling
units. Nearby views are not automatically independent. One scene cannot support a
cross-scene bootstrap. Resample actual independent units; insufficient replication
permits descriptive paired effects, not population confidence claims. Explicitly
distinguish interventions without recovery from end-to-end compression with recovery.
'''
