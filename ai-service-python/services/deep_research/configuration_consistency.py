"""Derived meanings of declared choices; never evidence or scientific approval."""
from collections import Counter
import json
import math

from services.deep_research.budget_spec import validate_budget_spec
from services.deep_research.execution_spec import execution_spec_errors
from services.deep_research.protocol_text import render_split

GENERATION = ('Text explains rationale/source boundaries; put exact split, state and budget settings '
    'in executionSpec only: the app renders them. Any prose setting MUST agree with its config. '
    'Account for every actual training phase, not one cap silently reused for omitted phases.')

GENERATION2 = ('Explain rationale/source boundaries; exact settings live in executionSpec and are rendered. '
    'Keep ALL text/conditions consistent when changing fields. Distinguish shared reference-model '
    'preparation from later learned-field fitting: fitting a field does not create its reference model. '
    'Define all representation/network states, compatible shapes/initial values and actual inputs, '
    'not one opaque parameter vector. Account for every fitting phase within finite caps; declare '
    'per-frame versus whole-window cost and temporal index mapping. Match whole-group training '
    'for isolated effects; a whole-stage cost tradeoff may use honest unmatched budgets, without '
    'claiming isolated parameter causality. Proposed choices need compatible implementation, not author attribution.')

PLANNING2 = ('Separate reference-model preparation, learned-field fitting and intervention in actual temporal '
    'order; one does not initialize the others. Plan complete representation/network states and available '
    'inputs, each fitting phase within finite caps, and per-frame versus whole-window costs. Preserve '
    'the source frame convention; proposed index mapping is not a source fact.')


def generation(version):
    return GENERATION2 if modern(version) else GENERATION


def align_grammar(text, version):
    """Correct instructions only; retain the original grammar for old requests."""
    if not modern(version):return text
    return text.replace('Unmatched confounds budgets.',
        'Unmatched cannot isolate parameter effects; whole-stage cost tradeoffs may use it with honest cost scope.').replace(
        'Scalar shape is []; constants broadcast compatibly;',
        'State initializer operation.rule requires NONEMPTY valid parameters describing its transformation, including copying. '
        'This differs from parameter-free creation/group actions. Scalar shape is []; constants broadcast compatibly;')


def align_repair(text, version):
    if not modern(version):return text
    old='''Propose finite compatible settings; never invent author facts/values or change the requested
technique to fit schema. Unsupported forms stay open. Define ALL states/initial values and
available inputs; no opaque weights/fake asset. Frame windows differ from held-out cameras;
eligibility uses training observations only. Whole-stage unmatched cost cannot isolate
parameter effects. Keep hypotheses future, pairing/aggregation executable and scope honest.'''
    new='''Keep method and future hypotheses.
Fix prose/conditions WITH configs. Match whole-group budgets for isolated effects;
whole-stage tradeoffs may use finite unmatched cost, not isolated causality.
Separate reference-model creation/field fitting; define ALL states/inputs/phases/caps.
State initializer operation.rule needs NONEMPTY parameters, even copying; creation
may be parameter-free. No opaque weights/fake assets. Training-only eligibility,
pairing/aggregation and bounded scope remain.'''
    # Original claims/context have already been serialized here. Only replace
    # this multiline system paragraph; single grammar phrases can occur inside
    # user/model content and must never be rewritten in a rendered request.
    return text.replace(old,new)

REVIEW = '''Derived configuration meanings below are calculations from proposed fields, NOT evidence
or approval. Compare ALL prose/conditions with these exact choices; reversed train/evaluation
assignments fail. Counts/availability remain unproven. Budget sums are upper caps only when the
declared units match: baseline preparation plus ONE declared whole-group recovery amount.
They neither multiply by an inferred frame count nor count shared preparation as separately
executed for each group. Do not require an extra total field forbidden by the exact schema.
Check per-frame vs whole-window scope, all actual fitting phases and narrative arithmetic;
the packet does not prove that those phases are covered. Equal arithmetic alone cannot fail
as an inconsistent sum; identify the actual incompatible field/phase/value instead. Preserve
source, initialization, intervention and measurement failures. No automatic verdict follows.'''


def enabled(value):
    return type(value) is int and value in (1,2)


def modern(value):
    return type(value) is int and value == 2


def facts(claims):
    """No prose parsing/eval, state mutation, invented counts or invalid-spec sums."""
    ids=Counter(c['claimId'] for c in claims if isinstance(c,dict)
        and isinstance(c.get('claimId'),str) and c['claimId'])
    result=[]
    for claim in claims:
        if (not isinstance(claim,dict) or not isinstance(claim.get('claimId'),str)
                or ids[claim['claimId']]!=1 or type(claim.get('designContractVersion')) is not int
                or claim['designContractVersion']!=2 or not isinstance(claim.get('kind'),str)
                or claim['kind'] not in {'proposal','suggestion','hypothesis'}):
            continue
        role=claim.get('designRole');spec=claim.get('executionSpec')
        row={'claimId':claim['claimId'],'role':role}
        if role=='data' and type(claim.get('protocolContractVersion')) is int and claim['protocolContractVersion']==2:
            try:errors=execution_spec_errors(role,spec)
            except (TypeError,ValueError,OverflowError):errors=['malformed_spec']
            if errors:row['schemaErrors']=errors
            elif spec['split']['mode']=='every_nth':
                row.update(fromPath=['executionSpec','split'],splitMeaning=render_split(spec['split']))
            else:continue  # Other schemes are already explicit; invent no sample lists.
        elif role=='budget' and type(claim.get('budgetContractVersion')) is int and claim['budgetContractVersion']==1:
            try:errors=validate_budget_spec(spec)
            except (TypeError,ValueError,OverflowError):errors=['malformed_spec']
            if errors:row['schemaErrors']=errors
            else:
                baseline,recovery=spec['baseline'],spec['recovery']
                row.update(fromPaths=[['executionSpec','baseline'],['executionSpec','recovery']],
                    baselineMode=baseline['mode'],recoveryUnit=recovery['unit'])
                if baseline['mode']=='train':
                    row['baselineUnit']=baseline['unit']
                    if baseline['unit']==recovery['unit']:
                        caps={}
                        for group,amount in recovery['groups'].items():
                            try:
                                total=baseline['maxBudget']+amount
                                if isinstance(total,float) and not math.isfinite(total):raise OverflowError
                                json.dumps(total,allow_nan=False)
                            except (TypeError,ValueError,OverflowError):
                                caps[group]={'notComputed':'unsupported_sum'}
                            else:caps[group]={'sum':[baseline['maxBudget'],amount],'upperCap':total}
                        row['perGroupUpperCaps']=caps
                    else:row['totalNotComputed']='different_units'
                else:row['totalNotComputed']='existing_asset_cost_not_declared'
        else:continue
        result.append(row)
    return result
