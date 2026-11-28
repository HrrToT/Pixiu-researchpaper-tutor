"""Versioned concise repair instructions; all original data remains lossless."""
import json
from services.deep_research.experiment_edits import columnar
from services.deep_research.nested_tables import claim_views


def render(**k):
    enc=lambda v:json.dumps(v,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    text=('Repair ONLY rejected targets; preserve IDs/kinds/roles/versions/context. '
        'Tables: zip columns/values, merge LAST extras. Nested executionSpec {"@":[columns,rows]} encodes arrays; '
        '{"!":object} escapes literal @/!. Restore real paths/values. Fix ALL checks/additionalChecks; '
        'former E labels must match current quotes/own permissions.\nQuestion:\n'+k['question']+k['length_contract'])
    for label,value in (
        ('Immutable accepted consistency context (not sources):',columnar(claim_views(k['accepted']))),
        ('UNVERIFIED siblings (not writable, not sources):',columnar(claim_views(k['siblings']))),
        ('Writable original claims:',columnar(claim_views(k['targets']))),
        ('ALL rejection checks:',columnar([k['checks'][r['claimId']] for r in k['targets']])),
        ('Schema feedback (syntax hints, NOT exhaustive/scientific corrections or approval):',k['diagnostics']),
        ('Missing questions (Q keys, not facts):',k['questions'])):
        text+='\n'+label+'\n'+enc(value)
    text+='\nAllowed own E IDs per target (permission, not support):\n'+k['permissions_marker']
    text+='\nExact original evidence/context/table data (lossless column table):\n'+k['evidence_marker']
    text+='\n'+k['source_instruction']+'\n'+k['table_instructions']
    # Keep the same edit schema so the unchanged coverage/parser checks apply.
    text+='''
Return ONLY [{"claimId":"writable ID","edits":[{"op":"replace|add|remove","path":"/text OR /executionSpec/... OR /evidenceRefs OR /conditions OR /detailLevel OR /tableBindings","value":"required except remove"}]}].
Pointers: ~0=tilde/~1=slash, zero-based arrays, add /- appends. Apply to ORIGINALS in order; omissions preserve values. Server restores/renders and independently rechecks; no acceptance/permission/budget exception.
Apply the system prospective policy. Preserve the requested technique; unsupported forms stay open. Separate reference-model preparation/field fitting; caps cover every phase and per-frame/window temporal mapping. Initializer operation rules need NONEMPTY parameters even for copying; creation may be parameter-free. Pair complete shared states. Final evaluation never initializes/trains/tunes/selects; eligibility uses training views. Frame windows differ from held-out cameras. Match whole-group budgets for isolated effects; unmatched whole-stage cost is not isolated causality. Pair observations/units and aggregation; keep inference scope honest.
Factual clauses/conditions cite OWN allowed visible E quotes; metadata/siblings are not support. Abstract sources support abstract facts only. E/P/Q labels stay out of published prose.
Opacity=不透明度α; transparency=1−α. Increasing α reduces transparency; optimization can raise OR lower α. Discrete sampling/index has no ordinary derivative: describe only the source-supported surrogate/coupled gradient path, not a differentiable index shortcut. Author intuitive cases are conditional, never universal update guarantees.
'''
    if k['declared_table_refs']:
        text+='For measured tableBindings use explicit SOURCE rowNumber (not selected-row position), zero-based groupIndex and exact own-source cells. Derived values are reasoning, not invented source cells.\n'
    if k.get('parameter_rows') is True:
        text+='Operation parameters accept objects, exact [name,type,value] rows or marked @ tables; server restores only these forms, preserving values/checks.'
    return text
