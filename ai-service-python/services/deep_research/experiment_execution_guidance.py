"""Executable proposed decisions and exact declaration pointers, never approvals."""
from collections import Counter
from copy import deepcopy


def enabled(record):
    return type(record.get('experimentExecutionGuidanceContractVersion')) is int and record['experimentExecutionGuidanceContractVersion']==1


PLANNING = '''Execution decisions: choose compatible UNEXECUTED settings now; absent author defaults
are not an unresolved prerequisite for a proposed value. Still cite actual method/data/asset facts.
state must name actual semantic tensors, dimensions, initialization inputs and network architecture;
an opaque flattened weights/model vector or all-zero aggregate is not a complete state.
pairingBudget must name EVERY fitting phase separately: initial reference preparation, learned
field fitting and intervention, each finite cap/unit and per-frame/per-window scope. Explain how
phase caps fit the typed aggregate cap; never give two phases the same undivided allowance.
measurement must choose reference, unit, view-then-unit aggregation, serialized byte boundaries,
timed region, device/resolution rule, concrete warmup, synchronization and repetitions. A future
record is not a chosen setting. Metrics are concrete prose; no extra metrics executionSpec exists.'''

DRAFTING = '''Implement the execution decisions, not placeholders. Distinguish creation from fitting:
declare actual training-data inputs and semantic states with compatible shapes/initial values,
including every required network layer/table. Derive variable dimensions from declared inputs;
never replace a representation by an unexplained NxD or flattened weights tensor. Preserve the
actual method; architecture choices beyond quoted facts must be explicit compatible proposals.
Keep individual fitting phases/caps in concrete prose under the exact existing budget schema;
their sum in the same unit must fit its aggregate cap, with separate temporal scopes. No hidden
preparation or shared phase counted twice. For metrics/limits, write the full executable protocol
in text/conditions, without inventing executionSpec fields. Choose measurement settings now;
include per-view then paired-unit aggregation, reference/range/units, byte accounting, timed
region, concrete warmup/synchronization/repeats and treatment of missing/nonfinite observations.'''


def data_declarations(claims):
    """Copy supplied data fields with exact paths; no schema/science verdict."""
    counts=Counter(c.get('claimId') for c in claims if isinstance(c,dict) and isinstance(c.get('claimId'),str))
    result=[]
    for claim in claims:
        if (not isinstance(claim,dict) or not isinstance(claim.get('claimId'),str)
                or counts[claim['claimId']]!=1 or claim.get('designRole')!='data'
                or claim.get('kind') not in ('proposal','suggestion','hypothesis')
                or type(claim.get('designContractVersion')) is not int or claim['designContractVersion']!=2
                or not isinstance(claim.get('executionSpec'),dict)):
            continue
        spec=claim['executionSpec']
        result.append({'claimId':claim['claimId'],'declaredFields':[
            {'path':['executionSpec',field],'value':deepcopy(spec[field])}
            for field in ('split','seeds','independentUnit','replication') if field in spec],
            'absentFields':[['executionSpec',field] for field in ('split','seeds','independentUnit','replication') if field not in spec]})
    return result


REVIEW = '''Exact data declarations below copy existing fields, not evidence or validation.
Do not call a present seed/split absent; explain its incompatible value, missing purpose or actual
source/availability defect separately. A present invalid/empty value still fails. Proposed ordinal
splits with prechecks need not invent original camera IDs/counts. Metrics/limits intentionally use
concrete prose, without an executionSpec grammar: audit exact quoted settings/omissions rather
than demand new schema keys. Read aggregation and phase choices across supplied linked statements.
No declaration, pointer or valid schema approves science or a rejected dependency.'''
