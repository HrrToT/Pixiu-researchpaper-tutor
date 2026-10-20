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
    return type(value) is int and value == 1


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
