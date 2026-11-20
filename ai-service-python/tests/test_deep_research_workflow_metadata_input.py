from copy import deepcopy
import json
import pytest

from services.deep_research import nested_tables, shared_strings
from services.deep_research.workflow_metadata_input import pack, unpack, input_text, POLICY
from services.deep_research.workflow_metadata_repair import prompt_for


def test_key_sharing_preserves_literals_markers_arrays_and_types():
    value = {'0': {'$': '0', '@': [None, True, False, 0, 1.5], '~': {'!': 'keys'}},
             'keys': ['value', '中文'], 'value': [{'0': 'not a reference'}]}
    before = deepcopy(value)
    assert unpack(pack(value)) == value == before


@pytest.mark.parametrize('key', ['-1', '01', '1', 'x', '١', True, 0])
def test_invalid_key_references_are_rejected_without_guessing(key):
    with pytest.raises(ValueError): unpack({'keys': ['field'], 'value': {key: 1}})


@pytest.mark.parametrize('keys', [['a', 'a'], [True], 'a', [1]])
def test_invalid_dictionary_is_rejected(keys):
    with pytest.raises(ValueError): unpack({'keys': keys, 'value': {}})


def test_full_repeated_input_roundtrips_and_saves_bytes_without_mutation():
    value = {'rows': [{'longSemanticFieldName': i, 'anotherLongSemanticFieldName':
        {'nestedOriginalSourceText': 'verbatim source ' * 8, 'uniqueText': str(i)}} for i in range(25)]}
    before = deepcopy(value)
    text = input_text(value)
    encoded = json.loads(text.splitlines()[0])
    decoded = nested_tables.unpack(shared_strings.unpack(encoded))
    assert unpack(decoded) == value == before
    assert len(text.encode()) < len(shared_strings.input_text(value).encode())
    assert 'Output uses the ordinary named schema' in text


def test_small_inputs_keep_existing_literal_or_shared_encoding():
    assert input_text({'a': 1}) == shared_strings.input_text({'a': 1})


def test_new_revision_adds_creation_semantics_without_changing_version8():
    from test_deep_research_workflow_metadata_repair import invalid_metadata
    meta = invalid_metadata(); feedback = {'issues': []}
    old = prompt_for('{}', meta, feedback, version=8)
    new = prompt_for('{}', meta, feedback, version=9)
    assert POLICY not in old and POLICY in new
    assert prompt_for('{}', meta, feedback, version=8) == old
    assert 'workflow_metadata_objects_v1' in new
