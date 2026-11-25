"""Resolve shared-plan references before applying the canonical plan checks."""

from copy import deepcopy
from itertools import islice

from jsonschema import Draft202012Validator

from services.deep_research.shared_experiment_plan import schema, validate


def wire_schema():
    wire = schema()
    states = wire['properties']['states']['items']['properties']
    input_source = states['source']
    input_source['properties']['kind'] = {'const': 'input'}
    states['source'] = {'anyOf': [input_source, {'type': 'null'}]}
    steps = wire['properties']['steps']['items']['properties']
    steps['operation'] = {'anyOf': [steps['operation'], {'type': 'null'}]}
    return wire


def compile_plan(value, evidence_ids, *, required_domains=()):
    errors = Draft202012Validator(wire_schema()).iter_errors(value)
    issues = [
        {'code': 'plan.wire_schema', 'path': '/' + '/'.join(map(str, error.absolute_path))}
        for error in islice(errors, 64)
    ]
    if issues:
        return None, issues

    proposal = deepcopy(value)
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
        elif owners:
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
