from copy import deepcopy
import pytest

from services.deep_research.planning_transport import options_for_record, descriptor_for, validate_options
from services.deep_research.workflow_metadata_repair import prompt_for
from test_deep_research_scientific_outline import record


def candidate(version):
    r = record()
    r.update(workflowMetadataRowsContractVersion=2, workflowMetadataRepairContractVersion=version)
    return r


@pytest.mark.parametrize('node', ['plan_workflow_meta', 'repair_workflow_meta'])
def test_metadata_reasoning_is_server_owned_and_frozen_before_request_identity(node):
    r = candidate(10)
    options = options_for_record(r, node, {'thinking': {'type': 'disabled'},
        'reasoning_effort': 'max', 'max_tokens': 1, 'timeout_seconds': 1})
    assert options['thinking'] == {'type': 'enabled'}
    assert options['reasoning_effort'] == 'low'
    assert options['max_tokens'] == 6144 and options['timeout_seconds'] == 90
    assert validate_options(r, node, options)
    for key, value in [('thinking', {'type': 'disabled'}), ('max_tokens', 1),
                       ('timeout_seconds', 1), ('reasoning_effort', 'max')]:
        altered = deepcopy(options); altered[key] = value
        assert not validate_options(r, node, altered)
    previous = options_for_record(candidate(9), node, {})
    assert previous['thinking'] == {'type': 'disabled'} and previous['reasoning_effort'] == 'none'
    assert previous['max_tokens'] == 3072
    assert options['response_format'] == previous['response_format'] == descriptor_for(r, node)


def test_initializer_and_entire_input_policy_remain_identical_to_version9():
    assert options_for_record(candidate(10), 'plan_workflow_init', {}) == options_for_record(
        candidate(9), 'plan_workflow_init', {})
    assert prompt_for('{}', {}, {}, 10) == prompt_for('{}', {}, {}, 9)


def test_only_version33_repair_uses_reasoning_and_reserves_its_whole_output_cap():
    r=candidate(33)
    options=options_for_record(r,'repair_workflow_meta',{'thinking':{'type':'disabled'},
        'reasoning_effort':'max','max_tokens':1,'timeout_seconds':1})
    assert options['thinking']=={'type':'enabled'} and options['reasoning_effort']=='low'
    assert options['max_tokens']==16384 and options['timeout_seconds']==90
    assert validate_options(r,'repair_workflow_meta',options)
    for key,value in [('thinking',{'type':'disabled'}),('reasoning_effort','max'),
                      ('max_tokens',6144),('timeout_seconds',180)]:
        altered=deepcopy(options);altered[key]=value
        assert not validate_options(r,'repair_workflow_meta',altered)
    old=options_for_record(candidate(32),'repair_workflow_meta',{})
    assert old['thinking']=={'type':'disabled'} and old['max_tokens']==6144
    assert options['response_format']==old['response_format']


@pytest.mark.parametrize('node',['plan_workflow_meta','plan_workflow_init'])
def test_version33_other_roles_keep_exact_options_from32(node):
    assert options_for_record(candidate(33),node,{})==options_for_record(candidate(32),node,{})


def test_version33_keeps_exact_prompt_and_fields_from32():
    assert prompt_for('{"source":"unaltered"}',{'authored':True},{'issues':[]},33)==prompt_for(
        '{"source":"unaltered"}',{'authored':True},{'issues':[]},32)
