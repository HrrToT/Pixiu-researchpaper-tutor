"""Resolve shared-plan references before applying the canonical plan checks."""

from copy import deepcopy
from itertools import islice

from jsonschema import Draft202012Validator

from services.deep_research.shared_experiment_plan import GROUPS, _array, _object, schema, validate


def wire_schema(profile=3, *, derive_pairing=False, derive_analysis=False, evaluation_prepare=False):
    wire = schema(3 if profile == 8 else 2 if profile in (4, 6, 7) else 1, evaluation_prepare=evaluation_prepare)
    if profile == 8 and derive_pairing:
        pairing = wire['properties']['pairing']
        for name in ('sharedStateIds', 'cloneStepIds'):
            del pairing['properties'][name]
            pairing['required'].remove(name)
    if profile == 8 and derive_analysis:
        analysis = wire['properties']['analysis']
        del analysis['properties']['metricIds']
        analysis['required'].remove('metricIds')
    states = wire['properties']['states']['items']['properties']
    input_source = states['source']
    input_source['properties']['kind'] = {'const': 'input'}
    step = wire['properties']['steps']['items']
    steps = step['properties']
    operation = steps['operation']
    steps['operation'] = {'anyOf': [operation, {'type': 'null'}]}
    if profile in (7, 8):
        step.update({
            'if': {'properties': {'kind': {'const': 'intervene'}}},
            'then': {'properties': {'operation': {'type': 'null'}, 'groups': {'const': []},
                                    'scope': {'const': 'arm'}, 'factor': steps['factor']['anyOf'][1]}},
            'else': {'properties': {'operation': {'type': 'object'}, 'factor': {'type': 'null'}}},
        })
    if profile == 3:
        states['source'] = {'anyOf': [input_source, {'type': 'null'}]}
        return wire

    owned = {key: value for key, value in states.items() if key not in ('scope', 'groups', 'source')}
    wire['properties']['states']['items'] = _object({**owned, 'source': input_source})
    wire['properties']['states']['minItems'] = 0
    steps['creates'] = _array(_object(owned))
    del steps['metricIds']
    wire['properties']['steps']['items']['required'].remove('metricIds')
    metric = wire['properties']['metrics']['items']
    metric['properties']['measureOnSteps'] = _array(states['id'], minimum=1, unique=True)
    metric['required'].append('measureOnSteps')
    if profile in (6, 7, 8):
        root = wire['properties']
        del root['states']
        wire['required'].remove('states')
        data = root['data']
        inputs = data['properties'].pop('inputs')
        asset = inputs['items']['properties']
        del asset['availability']
        data['required'].remove('inputs')
        data['properties'].update(
            providedInputs=_array(_object({**asset, 'initialStates': _array(_object(owned))}),
                                  maximum=inputs['maxItems']),
            inputsToPrepare=_array(_object(asset), maximum=inputs['maxItems']),
        )
        data['required'].extend(('providedInputs', 'inputsToPrepare'))
    return wire


def _expand_asset_catalog(proposal):
    data = proposal['data']
    proposal['states'] = []
    data['inputs'] = []
    for entry in data.pop('providedInputs'):
        for state in entry.pop('initialStates'):
            proposal['states'].append({**state, 'source': {'kind': 'input', 'id': entry['id']}})
        data['inputs'].append({**entry, 'availability': 'provided'})
    for entry in data.pop('inputsToPrepare'):
        data['inputs'].append({**entry, 'availability': 'prepare'})


def _expand_owned_states(proposal, issues):
    """Keep both the original input IDs and the actual creator for local review."""
    for state in proposal['states']:
        state.update(scope='shared', groups=[])

    steps = {step['id']: step for step in proposal['steps']}
    for index, step in enumerate(proposal['steps']):
        definitions = step['creates']
        step['creates'] = [state['id'] for state in definitions]
        step['metricIds'] = []
        for state in definitions:
            proposal['states'].append({
                **state, 'scope': step['scope'], 'groups': list(step['groups']),
                'source': {'kind': 'step', 'id': step['id']},
            })
        if step['kind'] == 'measure' and (step['creates'] or step['updates']):
            issues.append({'code': 'plan.measurement_mutation', 'path': f'/steps/{index}'})

    for index, metric in enumerate(proposal['metrics']):
        for step_id in metric.pop('measureOnSteps'):
            step = steps.get(step_id)
            if step is None or step['kind'] != 'measure':
                issues.append({'code': 'plan.measurement_reference', 'path': f'/metrics/{index}/measureOnSteps'})
                continue
            step['metricIds'].append(metric['id'])


def _separate_fit_observations(proposal):
    """Resolve a fit's newly captured observation, which is an output of that fit."""
    steps = proposal['steps']
    creators = {state_id: [index for index, step in enumerate(steps) if state_id in step['creates']]
                for metric in proposal['metrics'] for capture in metric['fitMemoryCaptures']
                for state_id in (capture['recordStateId'],)}
    interventions = [(index, step) for index, step in enumerate(steps) if step['kind'] == 'intervene']
    for metric in proposal['metrics']:
        for capture in metric['fitMemoryCaptures']:
            state_id = capture['recordStateId']
            owners = creators[state_id]
            if len(owners) != 1:
                continue
            index, = owners
            fit = steps[index]
            if (fit['id'] != capture['stepId'] or fit['kind'] != 'fit'
                    or state_id in fit['reads']
                    or any(position >= index or state_id in step['reads'] or state_id in step['updates']
                           for position, step in interventions)):
                continue
            fit['updates'] = [sid for sid in fit['updates'] if sid != state_id]
            for factor in proposal['factors']:
                factor['affectedStateIds'] = [sid for sid in factor['affectedStateIds'] if sid != state_id]


def _derive_pairing(proposal):
    """Use the actual clone reads as the shared starting state."""
    clones = [step for step in proposal['steps'] if step['kind'] == 'clone' and step['scope'] == 'arm']
    declared = {state['id'] for state in proposal['states'] if state['scope'] == 'shared'}
    shared = declared.intersection(*(step['reads'] for step in clones)) if clones else set()
    proposal['pairing'].update(sharedStateIds=sorted(shared), cloneStepIds=[step['id'] for step in clones])


def compile_plan(value, evidence_ids, *, required_domains=(), profile=3, fit_observation_outputs=False,
                 derive_pairing=False, derive_analysis=False, evaluation_prepare=False):
    errors = Draft202012Validator(wire_schema(profile, derive_pairing=derive_pairing,
                                             derive_analysis=derive_analysis,
                                             evaluation_prepare=evaluation_prepare)).iter_errors(value)
    issues = [
        {'code': 'plan.wire_schema', 'path': '/' + '/'.join(map(str, error.absolute_path))}
        for error in islice(errors, 64)
    ]
    if issues:
        return None, issues

    proposal = deepcopy(value)
    if profile == 8 and derive_analysis:
        # Shared work runs once before cloning. An explicit listing of all
        # four arms repeats its scope. Subsets still fail canonical validation.
        groups = set(GROUPS)
        for collection in ('steps', 'budgets'):
            for row in proposal[collection]:
                if row['scope'] == 'shared' and len(row['groups']) == len(groups) and set(row['groups']) == groups:
                    row['groups'] = []
        proposal['analysis']['metricIds'] = [metric['id'] for metric in proposal['metrics']]
    if profile in (6, 7, 8):
        _expand_asset_catalog(proposal)
    if profile in (7, 8):
        for step in proposal['steps']:
            if step['kind'] == 'intervene':
                factor = step['factor']
                axis = 0 if factor['id'] == 'A' else 1
                step['groups'] = [group for group in GROUPS if int(group[axis]) == factor['level']]
    if profile in (4, 6, 7, 8):
        _expand_owned_states(proposal, issues)
    if profile == 8 and derive_pairing:
        _derive_pairing(proposal)
    if profile == 8 and fit_observation_outputs:
        _separate_fit_observations(proposal)
    factors = {row['id']: row for row in proposal['factors']}
    provided_inputs = {row['id'] for row in proposal['data']['inputs'] if row['availability'] == 'provided'}
    creators = {}
    for step in proposal['steps']:
        for state_id in step['creates']:
            creators.setdefault(state_id, []).append(step['id'])

    for index, state in enumerate(proposal['states']):
        owners = creators.get(state['id'], [])
        path = f'/states/{index}/source'
        if state['source'] is None:
            if len(owners) == 1:
                state['source'] = {'kind': 'step', 'id': owners[0]}
            else:
                issues.append({'code': 'plan.state_creator_reference', 'path': path})
        elif state['source']['kind'] == 'input':
            if owners:
                issues.append({'code': 'plan.state_input_also_created', 'path': path})
            elif state['source']['id'] not in provided_inputs:
                issues.append({'code': 'plan.state_input_unavailable', 'path': path})

    for index, step in enumerate(proposal['steps']):
        path = f'/steps/{index}'
        if step['kind'] != 'intervene':
            if step['operation'] is None:
                issues.append({'code': 'plan.operation_required', 'path': path + '/operation'})
            continue
        if step['operation'] is not None:
            issues.append({'code': 'plan.intervention_operation_reference', 'path': path + '/operation'})
            continue
        selection = step['factor']
        if selection is None or set(factors) != {'A', 'B'}:
            issues.append({'code': 'plan.intervention_factor_reference', 'path': path + '/factor'})
            continue
        level = 'onOperation' if selection['level'] else 'offOperation'
        step['operation'] = deepcopy(factors[selection['id']][level])

    if issues:
        return None, issues
    issues = validate(proposal, evidence_ids, required_domains=required_domains)
    return (None if issues else proposal), issues
