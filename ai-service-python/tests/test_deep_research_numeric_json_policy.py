"""Producer-only numeric guidance; historical bytes and strict parsing stay fixed."""
import hashlib
import json

import pytest

from services.deep_research.structured_output import (
    ARRAY_NODES, DESIGN_REVIEW_NODES, PROSPECTIVE_JSON_POLICY,
    messages, messages_for_record, normalize,
)


@pytest.mark.parametrize('node',sorted(DESIGN_REVIEW_NODES|{'plan_experiment','synthesize','repair_claims'}))
def test_new_experimental_policy_preserves_evidence_and_original_framing(node):
    prompt='Exact source quote α; formulas and numbers are source data.'
    wire=messages_for_record({'structuredOutputContractVersion':9,
        'outputKind':'general','state':{'outputKind':'experiment_design'}},node,prompt)
    assert wire[-1]=={'role':'user','content':prompt}
    system=wire[0]['content']
    assert PROSPECTIVE_JSON_POLICY in system
    assert len(system.encode('utf8'))+128<=1024
    assert ('{"items":[]}' in system)==(node in ARRAY_NODES)


def test_historical_transport_bytes_are_frozen_including_experimental_v8():
    # Captured from the .224 source, before adding numeric policy v9.
    expected=[
        'd59a4656500a7a696004ad72736269ac1758c965b0ebb4f1dbcc46887b22d0ce',
        '9157dfc5b63403a56b1656b09e699595433f90522f3516a9428d34823fab41cc',
        '175da2d663554620d45312f10ca0d106aa62a41e6a2df1f0be3db21ab3b0216c',
        '9e9daf7d0eb247172c71f62f933a0848af622495e96149c3433bdfbcfa560a96',
        '51daaa415f58adcedd8adc5eac99418c34697275ef4d0dd521992b4fc6b0ac26',
        'e198cd1641f0028cb040b074967f4540fcba81d00ddd935a4cc28220614aa12d',
        '0e2b810351fe69030510329a110a5cedb5a3d4f7b80c2853114bd25dec189007',
        'beeeb62cf7d83e0eb6b4f9521bb7efde130716a8db326ce910a9fa9a40a53a32',
    ]
    # Freeze the original .224 node manifest as well as its byte checksums.
    # Newly introduced nodes never belonged to those historical requests.
    nodes=sorted({'plan','extract','assess_relevance','repair_claims','verify','verify_repair',
        'verify_design_science','verify_design_config','verify_repair_design_science',
        'verify_repair_design_config','verify_answer_coverage','resolve_brief','plan_experiment',
        'synthesize','synthesize_compact','synthesize_audience'})
    for version,checksum in enumerate(expected,1):
        data=[messages(n,'Literal α evidence',version,prospective=p) for n in nodes for p in (False,True)]
        raw=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()
        assert hashlib.sha256(raw).hexdigest()==checksum
    for node in set(nodes)-DESIGN_REVIEW_NODES-{'plan_experiment'}:
        assert messages(node,'Factual source',9)==messages(node,'Factual source',8)


@pytest.mark.parametrize('value',['2^19','2**19','1/2','NaN','Infinity'])
@pytest.mark.parametrize('template',['{"value":%s}','{"shape":[%s,2]}'])
def test_invalid_numeric_expression_is_not_evaluated_or_salvaged(value,template):
    raw=template%value
    result=normalize('synthesize',{'content':raw,'finishReason':'stop'})
    assert result['content']=='null' and result['rawContent']==raw
    assert result['structuredOutput']['receivedShape']=='invalid_json'


@pytest.mark.parametrize('value',['524288','0.5','-2','1e-3'])
def test_json_numeric_literals_and_schema_string_formulas_are_preserved(value):
    raw='{"value":'+value+',"analysis":{"effects":["A-B", "2^19"]}}'
    result=normalize('synthesize',{'content':raw,'finishReason':'stop'})
    assert result['content']==raw and result['rawContent']==raw
    assert result['structuredOutput']['receivedShape']=='object'
    assert json.loads(result['content'])['analysis']['effects']==['A-B','2^19']
