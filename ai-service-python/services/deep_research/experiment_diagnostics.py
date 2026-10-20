"""Actionable schema feedback, computed from originals; never a verdict or repair."""
from services.deep_research.state_initialization import STATE_EXPECTATIONS, state_definition_issues


RULES = {
    **STATE_EXPECTATIONS,
    'groups.fields': 'executionSpec has exactly factors:[{name,control:{action,parameters},treatment:{action,parameters}}]. Preserve the intended operations; choose actual parameters, not schema placeholders.',
    'controls.initialization': 'Exact {workflowClaimId:steps ID}; no checkpoint/state/extra keys. The referenced workflow alone defines initialization and must remain consistent with the budget.',
    'controls.workflow_link': 'Reference the supplied workflow-4 steps ID whose refs.controls points back to this control. A link is not approval of that workflow.',
    'budget.matched': 'matched requires equal whole-group recovery amounts. For a requested whole-stage cost comparison, unmatched requires an honest nonblank note and cannot claim an isolated parameter effect. Choose according to the objective, not merely to pass validation.',
    'workflow.fields': 'Workflow 4 exact keys: refs,order,baselineMode,replicationMode,baselineInitialization,componentInitializations,checkpointSelection,records.',
    'workflow.baseline_existing_creation': 'existing requires baselineInitialization:null and evidence for the selected available asset. Do not switch train to existing to avoid initialization.',
    'workflow.baseline_initialization': 'Train baseline requires exact {initializationMode,inputs,creation,stateDefinitions}. Define its actual complete initial state before fitting.',
    'workflow.baseline_mode_conflict': 'baselineMode must equal the referenced budget baseline.mode. Repair linked choices consistently; do not invent an available checkpoint or drop required baseline training.',
    'workflow.replication_mode_conflict': 'replicationMode must equal the referenced data replication.mode. Reusing one checkpoint is not independent baseline retraining.',
}


def feedback(claims, context=()):
    """JSON Pointers are relative to each original claim, not its rendered text."""
    from services.deep_research.experiment_workflow import workflow_errors
    from services.deep_research.experiment_protocol import protocol_errors
    from services.deep_research.group_spec import validate_group_spec
    from services.deep_research.budget_spec import validate_budget_spec
    indexed = {}
    for claim in [*context, *claims]:
        identity = claim.get('claimId')
        indexed[identity] = claim if identity not in indexed else None
    def lookup(identity):
        return indexed.get(identity) if isinstance(identity, str) else None
    targets, used = {}, set()
    for claim in claims:
        role, spec = claim.get('designRole'), claim.get('executionSpec')
        issues = []
        def add(path, code):
            issues.append([path, code]); used.add(code)
        if role == 'steps' and claim.get('workflowContractVersion') == 4 and isinstance(spec, dict):
            errors = workflow_errors(spec, 4)
            for code, path in (
                    ('workflow.fields', '/executionSpec'),
                    ('workflow.baseline_existing_creation', '/executionSpec/baselineInitialization'),
                    ('workflow.baseline_initialization', '/executionSpec/baselineInitialization')):
                if code in errors:
                    add(path, code)
            refs = spec.get('refs')
            if isinstance(refs, dict):
                for field, role_name, section in [('baselineMode', 'budget', 'baseline'),
                        ('replicationMode', 'data', 'replication')]:
                    sibling = lookup(refs.get(role_name))
                    sibling_spec = sibling.get('executionSpec') if isinstance(sibling, dict) else None
                    if (isinstance(sibling_spec, dict) and isinstance(sibling_spec.get(section), dict)
                            and spec.get(field) != sibling_spec[section].get('mode')):
                        add('/executionSpec/' + field, 'workflow.' + (
                            'baseline_mode_conflict' if field == 'baselineMode' else 'replication_mode_conflict'))
            definitions = [(spec.get('baselineInitialization'), '/executionSpec/baselineInitialization')]
            if isinstance(spec.get('componentInitializations'), list):
                definitions += [(component, f'/executionSpec/componentInitializations/{i}')
                    for i, component in enumerate(spec['componentInitializations'])]
            # Use the SAME state validator as production. No assumed dimension,
            # initial value, state name or scientific correction is supplied.
            for definition, path in definitions:
                if isinstance(definition, dict) and {'inputs', 'stateDefinitions'} <= definition.keys():
                    for issue in state_definition_issues(definition['stateDefinitions'], definition['inputs'],
                            path=path + '/stateDefinitions'):
                        add(issue['path'], issue['code'])
        elif role == 'controls' and claim.get('protocolContractVersion') == 2 and isinstance(spec, dict):
            errors = protocol_errors(role, spec, 2)
            if 'initialization.workflow_reference' in errors:
                add('/executionSpec/initialization', 'controls.initialization')
            elif not errors:
                target = lookup(spec.get('initialization', {}).get('workflowClaimId'))
                if (not isinstance(target, dict) or target.get('designRole') != 'steps'
                        or target.get('workflowContractVersion') != 4
                        or not isinstance(target.get('executionSpec'), dict)
                        or not isinstance(target['executionSpec'].get('refs'), dict)
                        or target['executionSpec']['refs'].get('controls') != claim['claimId']):
                    add('/executionSpec/initialization/workflowClaimId', 'controls.workflow_link')
        elif role == 'groups' and isinstance(spec, dict):
            if validate_group_spec(spec) and (set(spec) != {'factors'} or not isinstance(spec.get('factors'), list)):
                add('/executionSpec', 'groups.fields')
        elif role == 'budget' and claim.get('budgetContractVersion') == 1:
            if 'recovery: matched 模式要求所有组的预算值相等' in validate_budget_spec(spec):
                add('/executionSpec/recovery', 'budget.matched')
        if issues:
            targets[claim['claimId']] = issues
    return {'rules': {code: RULES[code] for code in sorted(used)}, 'targets': targets}
