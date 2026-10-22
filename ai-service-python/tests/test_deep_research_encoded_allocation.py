from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.experiment_outline_encoding import encode,validate,allocation_enabled
from services.deep_research.experiment_planning import prepare_draft
from services.deep_research.synthesis_evidence import fit_premises
from test_deep_research_outline_encoding import record,prompt
from test_deep_research_plan_encoding import store_for,prepare,padded_basis
from test_deep_research_experiment_planning import response


def rows():
    return [{'evidenceId':f'E{i}','quote':f'原文{i} α=0.1 不截断。','sourceContext':{'before':'Original condition.'}} for i in range(1,4)]


def render(values):
    return prompt(prefix='Exact original evidence:\n'+json.dumps(values,ensure_ascii=False,separators=(',',':'))+'\n')


def test_encoded_size_admits_all_required_sources_without_changing_rendered_content():
    r=record();r['experimentOutlineEncodingContractVersion']=2;original=rows();before=deepcopy(original)
    bundles=[{'evidenceIds':[row['evidenceId']]} for row in original]
    expected=[{**row,'sourceContext':{},'contextOmitted':True} for row in original]
    cap=len(encode(r,render(expected))[0].encode())
    raw,old,missing=fit_premises(original,render,bundles,max_bytes=cap)
    result,new,new_missing=fit_premises(original,render,bundles,max_bytes=cap,
        prompt_byte_size=lambda value:len(encode(r,value)[0].encode()))
    assert missing and len(old)<3 and not new_missing and new==expected
    assert result==render(expected) and len(result.encode())>cap
    assert len(encode(r,result)[0].encode())==cap and original==before
    assert all(row['quote']==before[i]['quote'] for i,row in enumerate(new))


def test_required_contexts_stay_whole_and_optional_context_never_displaces_them():
    r=record();r['experimentOutlineEncodingContractVersion']=2;original=rows();before=deepcopy(original)
    context={'before':'Exact necessary subject.','after':'Exact necessary condition.'}
    expected=[{**original[0],'sourceContext':context,'sourceContextRequired':True},
        *[{**row,'sourceContext':{},'contextOmitted':True} for row in original[1:]]]
    cap=len(encode(r,render(expected))[0].encode())
    result,new,missing=fit_premises(original,render,[{'evidenceIds':['E1','E2','E3']}],max_bytes=cap,
        required_contexts={'E1':context},prompt_byte_size=lambda value:len(encode(r,value)[0].encode()))
    assert not missing and new==expected and original==before
    assert new[0]['sourceContext']==context and new[0]['sourceContextRequired']
    assert len(encode(r,result)[0].encode())<=cap


@pytest.mark.parametrize('bad',[None,True,False,-1,'24000',float('inf'),0.5])
def test_invalid_byte_counter_results_stop_before_accepting_any_allocation(bad):
    with pytest.raises(ValueError,match='invalid_prompt_byte_size'):
        fit_premises(rows(),render,[],prompt_byte_size=lambda _:bad)


def test_wire_measurement_neither_invents_missing_sources_nor_increases_twenty_row_limit():
    original=[{'evidenceId':f'E{i}','quote':'Original text.'} for i in range(25)]
    _,new,missing=fit_premises(original,lambda values:json.dumps(values),
        [{'evidenceIds':['E99']}],prompt_byte_size=lambda value:len(value.encode()))
    assert len(new)==20 and missing==[{'evidenceIds':['E99']}]
    assert new==original[:20]


@pytest.mark.parametrize('version',[None,False,True,0,'2',1,3])
def test_encoded_allocation_is_strictly_contract_two(version):
    r=record();r['experimentOutlineEncodingContractVersion']=version
    assert not allocation_enabled(r)


def test_codec_one_remains_identical_and_audit_two_is_bound_to_its_own_contract():
    old=record();new=deepcopy(old);new['experimentOutlineEncodingContractVersion']=2
    a,aa=encode(old,prompt());b,bb=encode(new,prompt())
    assert a==b and aa['version']==1 and bb['version']==2
    assert {k:v for k,v in aa.items() if k!='version'}=={k:v for k,v in bb.items() if k!='version'}
    with pytest.raises(DeepResearchError):validate(new,b,aa)
    with pytest.raises(DeepResearchError):validate(old,a,bb)


def test_unknown_v1_plan_cannot_upgrade_to_v2_to_change_allocation_or_send_again():
    store=store_for(2);store.value.update(record());invoke=Mock(side_effect=OSError('unknown'))
    with pytest.raises(OSError):prepare(store,invoke)
    frozen=deepcopy(store.value['state']['experimentPlanning'])
    store.value['experimentOutlineEncodingContractVersion']=2;invoke.reset_mock()
    with pytest.raises(DeepResearchError,match='原输入'):prepare(store,invoke)
    invoke.assert_not_called();assert store.value['state']['experimentPlanning']==frozen


def test_actual_plan_overflow_still_fails_after_encoded_prefit():
    store=store_for(2);store.value.update(record());store.value['experimentOutlineEncodingContractVersion']=2
    saved=prepare(store,Mock(return_value=response(padded_basis(2859))))
    encoded,audit=encode(store.value,prompt(prefix='汉'*9000))
    with pytest.raises(DeepResearchError) as exc:
        prepare_draft(store.value,saved,prompt=encoded,checkpoint=store.checkpoint,outline_encoding_audit=audit)
    assert exc.value.code=='experiment_drafting_input_capacity'
    frozen=deepcopy(store.value['state']['experimentPlanning'])
    assert frozen['draftCapacity']['inputBytes']==len(encoded.encode())>24000
    assert frozen['outlineEncodingAudit']==audit and 'draftRequest' not in frozen


def test_graph_records_both_raw_and_wire_allocation_sizes_with_audited_final_body():
    from services.deep_research.graph import make_synthesize_node
    from test_deep_research_experiment_planning import Store
    from test_deep_research_lean_planning import lean_basis
    from test_deep_research_experiment_representation import wrapped_claims
    r=record();r['experimentOutlineEncodingContractVersion']=2;store=Store(r)
    invoke=Mock(side_effect=[response(lean_basis()),response({'sections':[],'claims':wrapped_claims()})])
    result=make_synthesize_node(invoke,store.update)({'run_id':'r'})
    assert not result.get('error_code') and invoke.call_count==2
    allocated=store.value['state']['synthesisPremiseAllocation']
    assert allocated['sizingContractVersion']==2 and allocated['encodedInputBytes']<=24000
    assert allocated['inputBytes']-allocated['encodedInputBytes']==269
    assert allocated['planningSlotReservedBytes']==2500
    saved=store.value['state']['experimentPlanning']
    validate(store.value,saved['draftRequest']['prompt'],saved['outlineEncodingAudit'])
    assert saved['outlineEncodingAudit']['encodedInputBytes']<=24000
