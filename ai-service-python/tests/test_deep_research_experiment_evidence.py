from copy import deepcopy
import hashlib,json
from unittest.mock import Mock
import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.experiment_evidence import build_context,enabled,expand,factor_registry
from services.deep_research.repair_scope import repair_evidence_scope
from services.deep_research.repair import _prepare_repair,_parse_repair_response,repair_rejected
from services.deep_research.verification import make_evidence,verify_claims


def inputs(kind='proposal'):
    file_hash=hashlib.sha256(b'paper bytes').hexdigest()
    passage='The tested method applies the stated operation before optimization.'
    source={'sourceId':'s','workId':'w','versionId':file_hash,'contentHash':hashlib.sha256(passage.encode()).hexdigest(),
        'ownerMaterialId':'m','sourceKind':'task_paper','accessLevel':'fulltext','text':passage,'obligationIds':['o']}
    evidence=make_evidence(source,passage,passage,location={'page':1},obligation_ids=['o'])
    evidence.update(sourceId='s',sourceKind='task_paper',sourceTitle='Actual paper')
    claim={'claimId':'c','kind':kind,'designRole':'limits','designContractVersion':2,
        'text':'Unverified prospective statement.','evidenceRefs':[],'obligationIds':['o']}
    record={'experimentEvidenceContractVersion':1,'sourcePolicy':{'mode':'task_only'},
        'materialSnapshot':{'materialRefs':['m'],'materialVersions':[{'id':'m','contentHash':file_hash}],
            'sourcePolicy':{'mode':'task_only'}},
        'materials':[{'materialId':'m','workId':'w','versionId':file_hash,'contentHash':file_hash}],
        'state':{'outputKind':'experiment_design','sources':[deepcopy(source)],'readResults':[deepcopy(source)],
            'plan':[{'obligations':[{'obligationId':'o','requiredSources':['m'],'question':'Bound the actual method.'}]}]}}
    return record,[claim],[evidence]


def candidates(record,claims,evidence,**kwargs):
    return expand(claims,evidence,repair_evidence_scope(claims,evidence),build_context(record),**kwargs)


@pytest.mark.parametrize('kind',['proposal','suggestion','hypothesis'])
def test_missing_original_citation_can_select_an_actually_read_own_source_without_approval(kind):
    record,claims,evidence=inputs(kind);before=deepcopy((record,claims,evidence))
    assert repair_evidence_scope(claims,evidence)=={'c':[]}
    assert candidates(record,claims,evidence)=={'c':[evidence[0]['evidenceId']]}
    assert (record,claims,evidence)==before
    assert evidence[0]['verification']=={'literal':'passed','semantic':'unchecked'}
    assert claims[0]['evidenceRefs']==[] and 'verification' not in claims[0]


@pytest.mark.parametrize('change',['abstract','literal_failed','empty_quote','unknown_source','wrong_work',
    'wrong_version','wrong_hash','wrong_publication','not_read','not_acquired','read_mismatch',
    'foreign_material','snapshot_hash_changed','material_version_changed','ambiguous_evidence',
    'ambiguous_source','ambiguous_requirement','wrong_required_source','unknown_obligation','missing_obligation',
    'wrong_design_role','old_design_contract','ambiguous_claim'])
def test_untrusted_unread_foreign_or_wrong_version_candidates_never_expand(change):
    record,claims,evidence=inputs();row=evidence[0]
    if change=='abstract':row['accessLevel']='abstract'
    elif change=='literal_failed':row['verification']['literal']='failed'
    elif change=='empty_quote':row['quote']=' '
    elif change=='unknown_source':row['sourceId']='foreign'
    elif change=='wrong_work':row['sourceWorkId']='foreign'
    elif change=='wrong_version':row['sourceVersionId']='wrong'
    elif change=='wrong_hash':row['contentHash']='changed'
    elif change=='wrong_publication':row['sourcePublicationIdentity']={'revision':'v99'}
    elif change=='not_read':record['state']['readResults']=[]
    elif change=='not_acquired':record['state']['sources']=[]
    elif change=='read_mismatch':record['state']['readResults'][0]['contentHash']='changed'
    elif change=='foreign_material':record['materialSnapshot']['materialRefs']=[]
    elif change=='snapshot_hash_changed':record['materialSnapshot']['materialVersions'][0]['contentHash']='changed'
    elif change=='material_version_changed':record['materials'][0]['versionId']='changed'
    elif change=='ambiguous_evidence':evidence.append({**row,'quote':'different same identity'})
    elif change=='ambiguous_source':record['state']['sources'].append({**record['state']['sources'][0],'contentHash':'changed'})
    elif change=='ambiguous_requirement':record['state']['plan'][0]['obligations'].append(
        {'obligationId':'o','requiredSources':['other'],'question':'Contradictory scope'})
    elif change=='wrong_required_source':record['state']['plan'][0]['obligations'][0]['requiredSources']=['foreign']
    elif change=='unknown_obligation':claims[0]['obligationIds']=['unknown']
    elif change=='missing_obligation':claims[0].pop('obligationIds')
    elif change=='wrong_design_role':claims[0]['designRole']='other'
    elif change=='old_design_contract':claims[0]['designContractVersion']=True
    elif change=='ambiguous_claim':claims.append(deepcopy(claims[0]))
    before=deepcopy((record,claims,evidence))
    result=candidates(record,claims,evidence)
    assert not result.get('c') and (record,claims,evidence)==before


def external_inputs():
    record,claims,evidence=inputs();record['materials']=[]
    record['materialSnapshot'].update(materialRefs=[],materialVersions=[],sourcePolicy={'mode':'external_only'})
    record['sourcePolicy']={'mode':'external_only'}
    for rows in ('sources','readResults'):
        source=record['state'][rows][0]
        source.update(workId='arxiv:2301.12345',versionId='arxiv:2301.12345v2',
            ownerMaterialId='arxiv:2301.12345',sourceKind='arxiv')
    evidence[0].update(sourceWorkId='arxiv:2301.12345',sourceVersionId='arxiv:2301.12345v2',sourceKind='arxiv')
    record['state']['plan'][0]['obligations'][0]['requiredSources']=['arxiv:2301.12345v2']
    return record,claims,evidence


def test_allowed_external_fulltext_is_pinned_and_read_and_task_only_cannot_enable_it():
    record,claims,evidence=external_inputs()
    assert candidates(record,claims,evidence)['c']==[evidence[0]['evidenceId']]
    record['sourcePolicy']['mode']='task_only'
    assert candidates(record,claims,evidence)=={'c':[]}
    record['sourcePolicy']['mode']='external_only';record['materialSnapshot']['sourcePolicy']['mode']='task_only'
    assert candidates(record,claims,evidence)=={'c':[]}


def test_requested_revision_wins_over_broad_work_name_and_other_revision_is_not_borrowed():
    record,claims,evidence=external_inputs()
    requirement=record['state']['plan'][0]['obligations'][0]
    requirement['requiredSources']=['arxiv:2301.12345','arxiv:2301.12345v1']
    assert candidates(record,claims,evidence)=={'c':[]}
    requirement['requiredSources']=['arxiv:2301.12345']
    assert candidates(record,claims,evidence)['c']
    for key in ('sources','readResults'):record['state'][key][0]['versionId']='arxiv:2301.12345'
    evidence[0]['sourceVersionId']='arxiv:2301.12345'
    assert candidates(record,claims,evidence)=={'c':[]}


def test_original_refs_are_preserved_but_extra_candidate_cap_stays_bounded():
    record,claims,evidence=inputs();original=deepcopy(evidence[0]);original['evidenceId']='existing'
    claims[0]['evidenceRefs']=['existing'];evidence=[original,*[
        {**deepcopy(evidence[0]),'evidenceId':'e'+str(i)} for i in range(20)]]
    result=candidates(record,claims,evidence)
    assert result['c'][0]=='existing' and len(result['c'])==13
    assert candidates(record,claims,evidence,max_additions=0)=={'c':['existing']}


def test_unspecified_sources_still_need_a_known_related_obligation_and_own_scope():
    record,claims,evidence=inputs()
    record['state']['plan'][0]['obligations'][0]['requiredSources']=[]
    assert candidates(record,claims,evidence)['c']
    evidence[0]['obligationIds']=['other']
    assert candidates(record,claims,evidence)=={'c':[]}


def test_scoped_candidates_enter_actual_prompt_with_source_identity_but_not_automatic_citations():
    record,claims,evidence=inputs();context=build_context(record)
    checks={'accepted':[],'rejected':[{'claimId':'c','reason':'semantic_unresolved','detail':'Cite actual method.'}]}
    prepared=_prepare_repair({'claims':claims},checks,evidence,'Design a bounded experiment.',
        experimental_intent=3,shared_experiment_schema=True,experiment_evidence_context=context)
    assert evidence[0]['quote'] in prepared['prompt'] and len(prepared['prompt'].encode())<=24000
    assert 'Original source registry (metadata only, not support or citations)' in prepared['prompt']
    assert 'Actual paper' in prepared['prompt'] and '"ownerMaterialId":"m"' in prepared['prompt']
    assert '"m":["P1"]' in prepared['prompt']
    assert prepared['allowed']['c']==[evidence[0]['evidenceId']]
    assert prepared['originals']['c']['evidenceRefs']==[]
    # Selecting a candidate does not attach it to the output automatically.
    output={'claimId':'c','kind':'proposal','designRole':'limits','text':'Bounded proposed conclusion.',
        'evidenceRefs':[],'conditions':{}}
    revised=_parse_repair_response(prepared,{'content':json.dumps([output])},json.loads,strict_response=True)
    assert revised[0]['evidenceRefs']==[]
    assert not verify_claims(revised,evidence)['accepted']
    output['evidenceRefs']=['foreign']
    assert _parse_repair_response(prepared,{'content':json.dumps([output])},json.loads,strict_response=True)==[]


def test_context_change_cannot_rewrite_a_pending_unknown_repair_request():
    record,claims,evidence=inputs();saved=[]
    checks={'accepted':[],'rejected':[{'claimId':'c','reason':'missing_evidence'}]}
    invoke=Mock(side_effect=RuntimeError('unknown; normal ledger prevents physical resend'))
    context=build_context(record)
    with pytest.raises(RuntimeError):repair_rejected({'claims':claims},checks,evidence,'Question',invoke,json.loads,
        experimental_intent=3,experiment_evidence_context=context,checkpoint=saved.append)
    changed=deepcopy(context);changed['requirements'][0]['requiredSources']=[]
    invoke.reset_mock()
    with pytest.raises(DeepResearchError,match='原始输入'):
        repair_rejected({'claims':claims},checks,evidence,'Question',invoke,json.loads,
            experimental_intent=3,experiment_evidence_context=changed,batch_state=saved[-1])
    invoke.assert_not_called()


def test_requirement_factoring_is_lossless_and_keeps_unavailable_source_identity():
    original={'sources':{'P1':{'sourceWorkId':'w','sourceVersionId':'v'}},'requirements':[
        {'obligationId':'a','requiredSources':{'w':['P1'],'missing':[]}},
        {'obligationId':'b','requiredSources':{'w':['P1'],'missing':[]}},
        {'obligationId':'c','requiredSources':{'different':[]}}]}
    before=deepcopy(original);factored=factor_registry(original)
    restored=[{'obligationId':oid,'requiredSources':group['requiredSources']}
        for group in factored['requirements'] for oid in group['obligationIds']]
    assert restored==original['requirements'] and factored['sources']==original['sources']
    assert len(factored['requirements'])==2 and original==before


def test_candidate_omitted_by_capacity_is_not_permitted_in_the_returned_revision():
    record,claims,evidence=inputs()
    text='Complete literal source text. '*1200
    value_hash=hashlib.sha256(text.encode()).hexdigest()
    for key in ('sources','readResults'):
        record['state'][key][0].update(text=text,contentHash=value_hash)
    source=record['state']['sources'][0]
    evidence=[{**make_evidence(source,text,text,location={'page':1},obligation_ids=['o']),
        'sourceId':'s','sourceKind':'task_paper'}]
    checks={'accepted':[],'rejected':[{'claimId':'c','reason':'missing_evidence'}]}
    prepared=_prepare_repair({'claims':claims},checks,evidence,'Question',experimental_intent=3,
        shared_experiment_schema=True,experiment_evidence_context=build_context(record))
    assert prepared['allowed']=={'c':[]} and len(prepared['prompt'].encode())<=24000
    output={'claimId':'c','kind':'proposal','text':'Unverified assertion.','evidenceRefs':['E1']}
    assert _parse_repair_response(prepared,{'content':json.dumps([output])},json.loads,strict_response=True)==[]


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_candidate_policy_is_server_owned_immutable_and_old_runs_do_not_opt_in(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        value,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Design an experiment',
            'experimentEvidenceContractVersion':replacement,'deferStart':True},start_async=False)
        assert value['experimentEvidenceContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(value['runId'],lambda r:{**r,'experimentEvidenceContractVersion':replacement})
    finally:facade.shutdown()
    record,_,_=inputs();record['experimentEvidenceContractVersion']=replacement
    assert not enabled(record) and build_context(record) is None
