"""Server-owned output grammar; does not certify an experiment's science."""
from services.deep_research.experiment_workflow import STAGES


def enabled(record, node):
    if node == 'repair_workflow_meta':
        from services.deep_research.workflow_metadata_repair import enabled as repair_enabled
        return repair_enabled(record)
    if (isinstance(record, dict) and type(record.get('executionWorkflowContractVersion')) is int
            and record['executionWorkflowContractVersion'] in (6,7)):
        return node in ('plan_workflow_meta', 'plan_workflow_init')
    return (node == 'plan_workflow' and isinstance(record, dict)
            and type(record.get('executionWorkflowContractVersion')) is int
            and record['executionWorkflowContractVersion'] in (3, 4, 5))


def descriptor(version=3):
    if type(version) is not int or version not in (3, 4, 5):
        raise ValueError('Unsupported workflow schema version')
    # Contract 5 changes model reasoning only; preserve the exact schema 4 wire.
    if version == 5:
        version = 4
    def obj(properties):
        return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)
    def arr(items, **limits):
        return dict(type='array', items=items, **limits)
    def ref(name):
        return {'$ref': '#/$defs/' + name}
    def enum(*values):
        return {'enum': list(values)}
    text = {'type': 'string', 'minLength': 1}
    number = {'type': 'number'}
    index = {'type': 'integer', 'minimum': 0}
    defs = {}
    defs['parameter'] = {'anyOf': [obj({'name': text, 'type': enum('number'), 'value': number}),
                                   obj({'name': text, 'type': enum('choice'), 'value': text})]}
    defs['operation'] = obj({'action': text, 'parameters': arr(ref('parameter'))})
    defs['rule'] = obj({'action': text, 'parameters': arr(ref('parameter'), minItems=1)})
    defs['seed'] = {'anyOf': [obj({'mode': enum('data_seed')}), obj({'mode': enum('fixed'), 'value': index})]}
    defs['literal'] = {'anyOf': [number, {'type': 'boolean'}, {'type': 'string'},
                                arr(ref('literal'), minItems=1)]}
    defs['initializer'] = {'anyOf': [
        obj({'mode': enum('constant'), 'value': ref('literal')}),
        obj({'mode': enum('uniform'), 'low': number, 'high': number, 'rng': text, 'seed': ref('seed')}),
        obj({'mode': enum('normal'), 'mean': number, 'std': {'type': 'number', 'exclusiveMinimum': 0},
             'rng': text, 'seed': ref('seed')}),
        obj({'mode': enum('operation'), 'inputIndices': arr(index, uniqueItems=True), 'rule': ref('rule')})]}
    defs['state'] = obj({'name': text, 'dtype': text,
        'shape': arr({'anyOf': [{'type': 'integer', 'minimum': 1},
                               obj({'inputIndex': index, 'axis': index})]}, maxItems=16),
        'initializer': ref('initializer')})
    creation = {'initializationMode': enum('fresh', 'derive'),
        'inputs': arr(obj({'state': text, 'selector': text})), 'creation': ref('operation'),
        'stateDefinitions': arr(ref('state'), minItems=1, maxItems=128)}
    defs['initialization'] = obj(creation)
    defs['component'] = obj({'componentId': text, **creation,
                             'appliesTo': arr(text, minItems=1, uniqueItems=True)})
    defs['split'] = {'anyOf': [
        obj({'mode': enum('every_nth'), 'order': text, 'stride': {'type': 'integer', 'minimum': 2}, 'offset': index}),
        obj({'mode': enum('seeded_fraction'), 'evaluationFraction': {'type': 'number', 'exclusiveMinimum': 0,
             'exclusiveMaximum': 1}, 'seed': index}),
        obj({'mode': enum('explicit'), 'train': arr(text, minItems=1, uniqueItems=True),
             'evaluation': arr(text, minItems=1, uniqueItems=True)})]}
    workflow = obj({'order': {'const': list(STAGES)}, 'baselineMode': enum('train', 'existing'),
        'replicationMode': enum('retrained_per_seed', 'fixed_checkpoint'),
        'baselineInitialization': {'anyOf': [{'type': 'null'}, ref('initialization')]},
        'componentInitializations': arr(ref('component')),
        'checkpointSelection': {'anyOf': [obj({'mode': enum('fixed_budget')}),
            obj({'mode': enum('train_loss'), 'rule': ref('rule')}),
            obj({'mode': enum('validation_split'), 'split': ref('split'), 'rule': ref('rule')})]},
        'records': arr(text, minItems=1, uniqueItems=True)})
    if version == 4:
        workflow['properties']['records'] = arr({'enum': [
            'baseline_identity', 'split_manifest', 'seed_manifest', 'component_states',
            'group_configs', 'recovery_budgets', 'evaluation_outputs', 'raw_measurements',
            'group_checkpoints']}, minItems=9, maxItems=9, uniqueItems=True)
    schema = obj({'sourceRefs': arr(text, maxItems=20, uniqueItems=True),
                  'workflow': workflow, 'unresolved': arr(text, maxItems=8)})
    schema['$defs'] = defs
    return {'type': 'json_schema', 'name': 'private_workflow_v' + str(version), 'schema': schema}


def reasoning_options(record, node, options):
    """Apply a frozen role policy before request identity and reservation."""
    if (node == 'plan_workflow_init' and enabled(record, node)
            and record['executionWorkflowContractVersion'] == 7
            and type(record.get('workflowInitializationOutputContractVersion')) is int
            and record['workflowInitializationOutputContractVersion'] == 1):
        # Keep the same schema/output cap/deadline; preserve legacy requests.
        return {**options, 'thinking': {'type': 'disabled'}, 'reasoning_effort': 'none'}
    if node in ('plan_workflow_meta', 'repair_workflow_meta'):
        from services.deep_research.workflow_metadata_repair import enabled as revision_enabled
        if (node == 'repair_workflow_meta' and revision_enabled(record)
                and record['workflowMetadataRepairContractVersion'] == 33):
            # Includes reasoning and visible output; reserved before the only repair.
            return {**options, 'thinking': {'type': 'enabled'}, 'reasoning_effort': 'low',
                    'max_tokens': 16384, 'timeout_seconds': 90}
        if revision_enabled(record) and record['workflowMetadataRepairContractVersion'] == 10:
            return {**options, 'thinking': {'type': 'enabled'}, 'reasoning_effort': 'low',
                    'max_tokens': 6144, 'timeout_seconds': 90}
    if enabled(record, node) and record['executionWorkflowContractVersion'] == 5:
        return {**options, 'thinking': {'type': 'enabled'}, 'reasoning_effort': 'low'}
    if enabled(record, node) and record['executionWorkflowContractVersion'] in (6,7):
        return {**options, 'thinking': {'type': 'enabled' if node == 'plan_workflow_init' else 'disabled'},
                'reasoning_effort': 'low' if node == 'plan_workflow_init' else 'none'}
    return options
