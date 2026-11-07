from copy import deepcopy
import json
import pytest

from services.deep_research.shared_strings import pack, unpack, input_text, LEGEND
from services.deep_research.contracts import digest


def test_repeated_original_strings_share_exact_values_without_mutating_input():
    data = {'evidence': [{'id': i, 'source': 'exact-long-source-identity-' * 3,
                         'quote': '原文 ' + str(i), 'number': 0.1, 'flag': False} for i in range(40)]}
    before = deepcopy(data)
    wire = pack(data)
    assert digest(unpack(wire)) == digest(data) and data == before
    assert len(json.dumps(wire).encode('utf8')) < len(json.dumps(data).encode('utf8'))
    unpack(wire)['evidence'][0]['id'] = 'changed'
    assert data == before


@pytest.mark.parametrize('literal', [{'$': 0}, {'~': {'$': 0}}, {'$': 1, 'x': '~'},
                                    {'~': {'~': {'$': 4}}}, {'@': [['x'], [[{'!': {'$': True}}]]]}])
def test_literal_markers_and_nested_table_markers_are_never_reinterpreted(literal):
    data = [literal, literal, 'repeated original string' * 3] * 6
    assert digest(unpack(pack(data))) == digest(data)


@pytest.mark.parametrize('reference', [True, -1, 1, '0', None])
def test_invalid_references_are_rejected(reference):
    with pytest.raises(ValueError): unpack({'strings': ['one'], 'value': {'$': reference}})


def test_selected_input_is_decodable_with_both_legends_and_keeps_plain_small_input():
    from services.deep_research.nested_tables import unpack as untables
    data = {'rows': [{'id': str(i), 'source': 'large repeated exact identity' * 3} for i in range(50)],
            'literal': {'@': [['x'], [[{'$': 0}]]]}}
    text = input_text(data)
    wire = json.loads(text.split('\n', 1)[0])
    assert text.endswith(LEGEND) and untables(unpack(wire)) == data
    assert input_text({'one': 1}) == '{"one":1}'
