"""Review the requested unexecuted estimand without waiving actual defects."""

POLICY = '''Prospective review contract 1: distinguish facts, choices and predictions per target.
Facts need OWN quoted support. Proposed choices need executable compatible settings, not
author attribution. A testable directional hypothesis needs no observed PSNR/SSIM gain;
reject disguised results/guarantees and invalid reasoning, not an unconfirmed prediction.
Match linked analysis/pairing and inference strength. Read shared definitions together.
If the USER studies a WHOLE stage/pipeline's quality/storage/extra-training tradeoff,
finite explicit unmatched optimization and honest costs may answer it. They cannot isolate
parameters from extra optimization; isolating effects still requires matched budgets.
Baseline training and per-frame recovery are separate phases; audit their own units/caps.
Proposed view enumeration/order/seed/split rules with nonempty/disjoint STOP prechecks need
no author camera indices or author-used-split quote. They prove no availability: dataset,
subset, named membership, asserted original counts and released assets still need evidence.
An explicit linked view-then-frame mean and per-frame pairing need no duplicate prose or
future enumerated view count. Still check reference images, seeds, units, storage boundary,
timing region/synchronization and compatibility; names/formulas do not fill missing methods.
Case/typography alone do not invalidate an unambiguous same name; variants remain distinct.
Failure reasons identify the exact target/linked field, actual missing/conflicting value
and required constraint. Syntax/context is NOT scientific approval; retain genuine source,
initialization, intervention and measurement failures.'''


def enabled(value):
    return type(value) is int and value in (1, 2, 3)


def policy(value):
    from services.deep_research.review_alignment import enabled, POLICY as aligned_policy
    return (aligned_policy if enabled(value) else POLICY) + ('' if value == 1 else '''
Typed audit contract 2: a slot may also be one exact {claimId,path,value} field binding,
equivalent to {fields:[that binding]}. The same existing path/value/role/contract checks
apply, including recovery for per_group_steps. This format is not scientific approval.''')
