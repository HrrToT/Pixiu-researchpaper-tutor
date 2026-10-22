from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError,digest
from services.deep_research.experiment_outline_encoding import encode,validate,enabled,MARKER,LEGEND,_outline
from services.deep_research.configuration_consistency import GENERATION2
from services.deep_research.experiment_edits import restore_columns
from services.deep_research.experiment_planning import prepare_draft
from test_deep_research_plan_encoding import store_for,prepare,padded_basis
from test_deep_research_experiment_planning import response


def record():
    r=store_for(2).value
    r.update(experimentOutlineEncodingContractVersion=1,configurationConsistencyContractVersion=2,
        experimentDraftContractVersion=6)
    return r


def prompt(prefix='Human question and exact quoted evidence.\n',suffix='\nExact full plan and sources stay here.'):
    return prefix+MARKER+json.dumps(_outline(),ensure_ascii=False,separators=(',',':'))+'\n'+GENERATION2+suffix


def test_all_roles_types_order_and_surrounding_question_source_plan_values_roundtrip_exactly():
    original=prompt(prefix='Question quotes the entire system paragraph:\n'+prompt()+'\nActual draft:\n',
        suffix='\n{"quote":"Keep E7 and α=0.1; do not execute `code`","plan":[true,1,"汉字"]}')
    before=original;new,audit=encode(record(),original)
    assert new.startswith(original[:original.rfind(MARKER)]) and new.endswith('"汉字"]}')
    assert restore_columns(audit['encodedOutline'])==audit['originalOutline']==_outline()
    assert audit['originalPromptDigest']==digest(original) and audit['scientificApproval'] is False
    assert audit['encodedInputBytes']<audit['originalInputBytes'] and original==before
    validate(record(),new,audit)


@pytest.mark.parametrize('version',[None,False,True,0,'1',2,3])
def test_legacy_unknown_and_wrong_type_versions_keep_exact_request(version):
    r=record();r['experimentOutlineEncodingContractVersion']=version
    original=prompt();assert not enabled(r) and encode(r,original)==(original,None)
    validate(r,original,None)


@pytest.mark.parametrize('change',['original_bool','encoded_bool','original_role','encoded_role','source_digest',
    'encoded_digest','source_bytes','encoded_bytes','bool_bytes','approval','bool_version','extra'])
def test_tampering_never_becomes_an_accepted_outline_or_request(change):
    r=record();new,audit=encode(r,prompt());audit=deepcopy(audit)
    if change=='original_bool':audit['originalOutline'][0]['requiresExecutionSpec']=1
    elif change=='encoded_bool':audit['encodedOutline']['rows'][0][3]=1
    elif change=='original_role':audit['originalOutline'].pop()
    elif change=='encoded_role':audit['encodedOutline']['rows'].pop()
    elif change=='source_digest':audit['originalPromptDigest']='other'
    elif change=='encoded_digest':audit['encodedPromptDigest']='other'
    elif change=='source_bytes':audit['originalInputBytes']+=1
    elif change=='encoded_bytes':audit['encodedInputBytes']+=1
    elif change=='bool_bytes':audit['encodedInputBytes']=True
    elif change=='approval':audit['scientificApproval']=True
    elif change=='bool_version':audit['version']=True
    else:audit['approved']=True
    with pytest.raises(DeepResearchError,match='目录'):validate(r,new,audit)


def test_missing_system_outline_cannot_be_replaced_by_quoted_fake_or_truncated_structure():
    r=record()
    with pytest.raises(DeepResearchError):encode(r,'Quoted JSON: '+json.dumps(prompt()))
    with pytest.raises(DeepResearchError):encode(r,prompt().replace('"designRole":"groups"','"designRole":"unknown"'))


def test_unknown_planning_request_cannot_opt_into_new_generation_framing():
    store=store_for(2);store.value.update(configurationConsistencyContractVersion=2,experimentDraftContractVersion=6)
    invoke=Mock(side_effect=OSError('unknown'))
    with pytest.raises(OSError):prepare(store,invoke)
    frozen=deepcopy(store.value['state']['experimentPlanning'])
    store.value['experimentOutlineEncodingContractVersion']=1;invoke.reset_mock()
    with pytest.raises(DeepResearchError,match='原输入'):prepare(store,invoke)
    invoke.assert_not_called();assert store.value['state']['experimentPlanning']==frozen


def test_new_frozen_draft_preserves_audit_and_late_reuse_without_silent_audit_replacement():
    store=store_for(2);store.value.update(record());saved=prepare(store,Mock(return_value=response(padded_basis(2859))))
    new,audit=encode(store.value,prompt());request=prepare_draft(store.value,saved,prompt=new,
        checkpoint=store.checkpoint,outline_encoding_audit=audit)
    frozen=deepcopy(store.value['state']['experimentPlanning']);assert frozen['outlineEncodingAudit']==audit
    late=deepcopy(store.value);late['budget']['elapsedSeconds']=350
    assert prepare_draft(late,frozen,prompt=new,checkpoint=store.checkpoint,outline_encoding_audit=audit)==request
    wrong=deepcopy(frozen);wrong['outlineEncodingAudit']['scientificApproval']=True
    with pytest.raises(DeepResearchError):prepare_draft(store.value,wrong,prompt=new,checkpoint=store.checkpoint,outline_encoding_audit=audit)
    assert store.value['state']['experimentPlanning']==frozen


def test_encoding_does_not_bypass_whole_request_capacity_or_change_a_known_refusal():
    store=store_for(2);store.value.update(record());saved=prepare(store,Mock(return_value=response(padded_basis(2859))))
    new,audit=encode(store.value,prompt(prefix='汉'*9000))
    with pytest.raises(DeepResearchError) as exc:
        prepare_draft(store.value,saved,prompt=new,checkpoint=store.checkpoint,outline_encoding_audit=audit)
    assert exc.value.code=='experiment_drafting_input_capacity'
    frozen=deepcopy(store.value['state']['experimentPlanning'])
    assert frozen['draftCapacity']['inputBytes']==len(new.encode()) and frozen['outlineEncodingAudit']==audit
    shorter,short_audit=encode(store.value,prompt())
    with pytest.raises(DeepResearchError):prepare_draft(store.value,frozen,prompt=shorter,checkpoint=store.checkpoint,outline_encoding_audit=short_audit)
    assert store.value['state']['experimentPlanning']==frozen


def test_graph_encodes_after_fitting_preserving_the_selected_evidence_and_plan():
    from services.deep_research.graph import make_synthesize_node
    from test_deep_research_experiment_planning import Store
    from test_deep_research_lean_planning import lean_basis
    from test_deep_research_experiment_representation import wrapped_claims
    results=[]
    for modern in (False,True):
        r=record()
        if not modern:r.pop('experimentOutlineEncodingContractVersion')
        store=Store(r);invoke=Mock(side_effect=[response(lean_basis()),response({'sections':[],'claims':wrapped_claims()})])
        result=make_synthesize_node(invoke,store.update)({'run_id':'r'})
        assert not result.get('error_code');results.append((store.value,invoke.call_args_list))
    old,new=results
    assert old[0]['state']['synthesisPremiseAllocation']==new[0]['state']['synthesisPremiseAllocation']
    assert old[1][0].args==new[1][0].args  # Physical planning prompt/options unchanged.
    assert LEGEND not in new[1][0].args[2] and LEGEND in new[1][1].args[2]
    assert old[0]['state']['reportBody']==new[0]['state']['reportBody']
    assert new[0]['state']['experimentPlanning']['outlineEncodingAudit']['originalPromptDigest']==digest(old[1][1].args[2])


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_outline_contract_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'runs.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        value,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Propose an experiment',
            'experimentOutlineEncodingContractVersion':replacement,'deferStart':True},start_async=False)
        assert value['experimentOutlineEncodingContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(value['runId'],lambda r:{**r,'experimentOutlineEncodingContractVersion':replacement})
    finally:facade.shutdown()
