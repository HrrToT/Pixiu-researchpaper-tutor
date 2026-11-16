"""Send frozen, unapproved representation decisions to the actual design audit."""
from copy import deepcopy

from services.deep_research.contracts import DeepResearchError, digest


POLICY = '''Shared representation is a model-authored, SCIENTIFICALLY UNVERIFIED design,
not source evidence, existing instances or dependency approval. Read it together with
the bound steps and other operational definitions. Independently enumerate required
numeric variables; audit physical/stored domains, transforms/inverses, units, channels,
basis, normalization, dtype and dimensions against actual initializers, acquisition,
rendering and update operations. Compatible proposed choices need no author attribution;
origin:paper requires the entry's OWN supplied original quotes. Reject opaque containers,
missing states, contradictory conventions and unresolved prerequisites that prevent
execution. A structurally frozen definition is not scientifically accepted. Judge only
the actual target claims; a dependent target cannot pass by assuming this context valid.
Keep the existing audit schema, evidence rules and verdict/dependency gates.'''


def remap_refs(value, aliases):
    """Translate typed sourceRefs only; never rewrite source text or formulas."""
    if isinstance(value, list):
        return [remap_refs(item, aliases) for item in value]
    if isinstance(value, dict):
        return {key: [aliases[ref] for ref in item] if key == 'sourceRefs'
                else remap_refs(item, aliases) for key, item in value.items()}
    return deepcopy(value)


def context(record, claims, proposal_context):
    from services.deep_research.workflow_representation_stage import MARKER, enabled, bound
    if (not enabled(record) or type(record.get(MARKER)) is not int or record[MARKER] != 4
            or not any(c.get('designContractVersion') == 2 and c.get('designRole')
                       and c.get('kind') in {'proposal', 'suggestion', 'hypothesis'} for c in claims)):
        return None
    try:
        blueprint = record['state']['executionWorkflowBlueprint']
        binding = record['state']['executionWorkflowBinding']
        if (blueprint['status'] != 'ready' or blueprint['scientificApproval'] is not False
                or blueprint['request']['representationContract'] != 4
                or digest(blueprint['value']) != blueprint['valueDigest']
                or binding['blueprintDigest'] != blueprint['valueDigest']
                or binding['scientificApproval'] is not False):
            raise ValueError('Unbound workflow')
        steps_id = binding['claimIds']['steps']
        steps = [c for c in [*claims, *proposal_context] if c.get('claimId') == steps_id]
        if len(steps) != 1 or steps[0].get('designRole') != 'steps':
            raise ValueError('Missing actual steps claim')
        expected = {**deepcopy(blueprint['value']['workflow']),
                    'refs': {k: v for k, v in binding['claimIds'].items() if k != 'steps'}}
        if digest(steps[0].get('executionSpec')) != digest(expected):
            raise ValueError('Steps changed from bound workflow')
        stage = blueprint['representation']
        first_target = stage['value']['targets'][0]['target']
        frozen, metadata, aliases = bound(record, first_target)
        from services.deep_research.workflow_representation import verify
        value = verify(frozen, metadata, aliases)
        if digest(stage['response']) != stage['responseDigest']:
            raise ValueError('Representation response changed')
        from services.deep_research.workflow_representation_slots import decode, metadata_for_record
        from services.deep_research.workflow_metadata_repair import load_wire
        if metadata_for_record(record) != metadata:
            raise ValueError('Metadata receipt changed')
        response = stage['response']
        if (response.get('finishReason', response.get('finish_reason')) != 'stop'
                or decode(load_wire(response.get('rawContent', response.get('content', '')), version=3), metadata) != value):
            raise ValueError('Representation differs from received response')
        return {'stepsClaimId': steps_id, 'blueprintDigest': blueprint['valueDigest'],
                'declarationDigest': frozen['valueDigest'], 'scientificApproval': False,
                'sharedRepresentation': remap_refs(value, aliases)}
    except (KeyError, TypeError, ValueError, IndexError, RecursionError) as exc:
        raise DeepResearchError('invalid_representation_review_binding',
                                '共享表示与实际方案的核验绑定无效，尚未发送。') from exc


def evidence_refs(view):
    return view['sharedRepresentation']['sourceRefs'] if view else []
