"""Index actual review fields, without interpreting their scientific meaning."""
from collections import Counter

from services.deep_research.rejection_audit import ROOTS


def field_index(claims):
    counts = Counter(c.get('claimId') for c in claims if isinstance(c, dict)
                     and isinstance(c.get('claimId'), str))
    rows = []
    for claim in claims:
        if (not isinstance(claim, dict) or not isinstance(claim.get('claimId'), str)
                or counts[claim['claimId']] != 1
                or claim.get('kind') not in ('proposal', 'suggestion', 'hypothesis')
                or type(claim.get('designContractVersion')) is not int
                or claim['designContractVersion'] != 2):
            continue
        role = claim.get('designRole')
        if not isinstance(role, str) or role not in {*ROOTS, 'metrics', 'limits'}:
            continue
        spec = claim.get('executionSpec')
        rows.append({
            'claimId': claim['claimId'], 'role': role,
            'present': [key for key in ('text', 'conditions', 'executionSpec') if key in claim],
            'specKeys': sorted(spec) if isinstance(spec, dict) else None,
            'missingSpecKeys': sorted(ROOTS[role] - set(spec))
                if role in ROOTS and isinstance(spec, dict) else None,
            'proseOnlyRole': role in ('metrics', 'limits'),
        })
    return rows


POLICY = '''Review the supplied target; do NOT choose replacement settings or strengthen the task.
First distinguish (a) attributed paper/data/asset facts needing OWN evidence, (b) explicitly
proposed settings needing operational compatibility, and (c) the requested inference. A proposed
budget/rate/resize is not unsupported merely because authors did not report it. Source method
operations and claimed original values remain factual; "proposed" cannot excuse replacing them.
The field index is structural only. Follow actual keys into the unchanged claims above, including
linked text AND conditions. Missing means absent, not present-but-invalid or an unwanted value.
Metrics/limits intentionally have no executionSpec: bind their actual text/conditions. Analysis
formulas live in effects; descriptive aggregation may live in uncertainty.boundary and prose.
Budget baseline and recovery are separate; read explicit shared phases and temporal caps in prose
before claiming a phase absent. Exact keys do not prove coverage or compatibility. Check the real
state/inputs, method, data, measurement, pairing and inference; no automatic passes or dependence
on a rejected sibling. Each rejection names its actual conflicting value and applicable rule,
not a hypothetical extra key, a duplicate definition or a future result.'''


PROSPECTIVE_POLICY = '''Classify the exact clause BEFORE judging support:
1. Paper facts, method operations, dataset membership, original values and released assets
need OWN source evidence. A proposal label never licenses inventing or replacing these facts.
2. A hypothesis predicts an UNOBSERVED contrast. Judge falsifiability, relevant source-based
motivation, pairing, measurement and inference; do NOT require papers to have already observed
the predicted PSNR/SSIM gain. Directional predictions are allowed; fabricated observations,
guaranteed gains and unsupported factual premises are not. Read kind, role AND conditions.
3. Explicit proposed seeds/rates/thresholds/budgets need concrete compatible choices, not proof
authors used those numbers. Reject a real incompatibility or disguised original-value claim;
"not reported in E" alone does not reject a proposed setting.
Review the supplied objective, not a stronger task. Before any missing/incomplete finding,
read linked text/conditions/config; name what remains absent or invalid despite those values.
Never report warmup/repeats/units missing when supplied. Do not demand duplicate definitions.
''' + POLICY[POLICY.index('The field index is structural only.'):]
