"""Repair input2 deduplicates trusted instructions, keeping every data block."""
import json
from services.deep_research.experiment_edits import columnar
from services.deep_research.nested_tables import claim_views

SOURCE_LABEL='\nOriginal source registry (metadata only, not support or citations):\n'
SOURCE_TAIL=('\nEach requirement group applies its requiredSources mapping to every listed obligationId. '
    'P IDs identify exact work/version/access/ownership. publicationIdentity pins the publication revision, '
    'not a scientific fact. Each factual clause still needs its OWN supplied E quotations.\n')


def source_instruction(text):
    """Factor only this exact server paragraph, never question/registry strings."""
    if not text.startswith(SOURCE_LABEL):return text
    try:
        _,end=json.JSONDecoder().raw_decode(text[len(SOURCE_LABEL):])
    except (ValueError,TypeError):return text
    position=len(SOURCE_LABEL)+end
    if text[position:]!=SOURCE_TAIL:return text
    return (text[:position]+'\nGroups map requiredSources to ALL listed obligationIds. P=work/version/access/owner; '
        'publicationIdentity=revision, not fact. Factual clauses need OWN E quotes.\n')


def render(**k):
    enc=lambda v:json.dumps(v,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    text=('Only targets writable; keep IDs/kinds/roles/versions. '
        'Tables: zip columns/values, merge last extras. executionSpec {"@":[keys,rows]}=arrays; '
        '{"!":object}=literal @/!. Expand exact paths/values. Fix ALL checks/additionalChecks. '
        'Former E IDs need current own-quote permission.\nQuestion:\n'
        +k['question']+k['length_contract'])
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
    text+='\n'+source_instruction(k['source_instruction'])+'\n'+k['table_instructions']
    text+='''
Return ONLY [{"claimId":"writable ID","edits":[{"op":"replace|add|remove","path":"/text OR /executionSpec/... OR /evidenceRefs OR /conditions OR /detailLevel OR /tableBindings","value":"required except remove"}]}].
Pointers apply to ORIGINALS in order; omissions stay. ~0=tilde, ~1=slash; zero-based indices;
add /- appends. Server rechecks.
Apply system policy/role grammar; no invented budget keys. Keep method, ALL state inputs/values,
separate preparation/field-fitting caps and frame/window scopes, paired copies/observations,
units/aggregation and bounded inference. Initializer rules need NONEMPTY parameters even for
copy; creation may be parameter-free. Evaluation never initializes/trains/tunes/selects;
eligibility uses training views; frames differ from held-out cameras. Isolated effects match
whole-group budgets; unmatched whole-stage costs cannot isolate parameters. Abstracts support
abstract facts only; no E/P/Q prose. Metadata/siblings are not evidence.
Opacity=不透明度α; transparency=1−α; increasing α lowers transparency, optimization may move
either way. Discrete indices lack ordinary derivatives: only source-supported surrogate/coupled
paths, no differentiable-index shortcut or universal guarantee from intuitive conditional cases.
'''
    if k['declared_table_refs']:
        text+='tableBindings: actual SOURCE rowNumber, zero-based groupIndex, own E/cells only.\n'
    return text
