from copy import deepcopy
import json
import pytest
from services.deep_research.request_coverage import prompt,focus_answer,decision_inputs
from services.deep_research.shared_strings import unpack
from services.deep_research.nested_tables import unpack as untables


def fixture():
    phrase='必须完整保留的研究条件和原始问题。'*30
    requirements=[{'obligationId':'o','question':phrase,'checks':[{'checkId':'c','requirement':phrase}]}]
    claims=[{'claimId':'c','kind':'inference','text':phrase,'conditions':{},'evidenceRefs':['e']}]
    metadata={'label':phrase,'literal':{'$':'unchanged','@':['literal']}}
    return phrase,requirements,claims,metadata


def test_shared_decision_payload_roundtrips_every_original_value():
    q,req,claims,metadata=fixture();original=deepcopy((q,req,claims,metadata))
    rendered=decision_inputs(q,req,claims,metadata,shared_inputs=True)
    wire=json.loads(rendered.splitlines()[1])
    value=untables(unpack(wire)) if set(wire)=={'strings','value'} else wire
    assert value=={'question':q,'requirements':req,'claims':claims,'metadata':metadata}
    assert (q,req,claims,metadata)==original
    assert len(rendered.encode())<len(decision_inputs(q,req,claims,metadata).encode())


@pytest.mark.parametrize('shared',[False,True])
def test_focus_preserves_exact_input_and_rejects_changed_claims(shared):
    q,req,claims,metadata=fixture();kwargs={'shared_inputs':True} if shared else {}
    value=prompt(q,req,claims,metadata,'EVIDENCE','fixed scientific policy',**kwargs)
    moved=focus_answer(value,q,req,claims,metadata,**kwargs)
    assert moved.endswith(decision_inputs(q,req,claims,metadata,**kwargs))
    assert 'fixed scientific policy' in moved and 'EVIDENCE' in moved
    with pytest.raises(ValueError,match='serialized prefix'):
        focus_answer(value,q,req,[{**claims[0],'text':'changed'}],metadata,**kwargs)


def test_legacy_default_is_byte_identical_to_explicit_false():
    q,req,claims,metadata=fixture()
    assert prompt(q,req,claims,metadata,'E','policy')==prompt(q,req,claims,metadata,'E','policy',shared_inputs=False)


@pytest.mark.parametrize('bad',[1,'true',None])
def test_input_policy_is_strict_bool(bad):
    with pytest.raises(ValueError,match='policy'):decision_inputs(*fixture(),shared_inputs=bad)


@pytest.mark.parametrize('replacement',[None,0,True,'1',2])
def test_root_contract_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'o','question':'比较论文',
                            'coverageInputContractVersion':replacement,'deferStart':True},start_async=False)
        assert run['coverageInputContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'coverageInputContractVersion':replacement})
    finally:facade.shutdown()


@pytest.mark.parametrize('kind',['experiment_design','unsupported_kind'])
def test_non_request_coverage_modes_keep_original_verification_path(kind):
    from services.deep_research.graph import make_verify_node
    record={'coverageInputContractVersion':1,'requestCoverageContractVersion':5,'question':'研究问题',
            'state':{'outputKind':kind,'reportBody':{'claims':[]},'evidence':[]},'budget':{}}
    def update(rid,fn,**kwargs):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    make_verify_node(lambda *a:{'accepted':[],'rejected':[]},None,update)({'run_id':'r'})
    assert 'verifiedReport' in record['state']
    assert 'coverageInputContractVersion' not in record['state']['verifiedReport']['answerCoverage']
