from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.audience_publication_budget import allocation,enabled,fits
from services.deep_research.audience_rewrite import rewrite_for_beginner
from services.deep_research.answer_constraints import visible_count
from services.deep_research.contracts import DeepResearchError
from test_deep_research_audience_edit_budget import fixture,answer,options

CTX={'outputKind':'claim_verification','presentationVersion':4}


def test_budget_reserves_fixed_points_and_actual_publication_labels():
    report,ev,q=fixture();before=deepcopy((report,ev));b=allocation(report,ev,q,CTX,['fixed'])
    shadow=deepcopy(report);shadow['claims'][0].update(text='',conditions={})
    assert b['reservedCharacters']==visible_count(shadow,100,'claim_verification',ev,4)
    assert b['reservedCharacters']>b['fixedCharacters']
    assert b['editableCharacters']==100-b['reservedCharacters']
    assert b['layoutCharacters']==b['reservedCharacters']-b['fixedCharacters']
    states=[];invoke=Mock(return_value=answer())
    result=rewrite_for_beginner(report,ev,q,invoke,json.loads,checkpoint=states.append,publication_context=CTX,**options())
    prompt=invoke.call_args.args[0]
    assert f"fit {b['editableCharacters']} characters" in prompt
    assert states[0]['publicationBudget']==b and states[0]['editBudget']['editableCharacters']==b['editableCharacters']
    assert states[0]['editBudget']['layoutCharacters']==b['layoutCharacters']
    assert result['claims'][1]==report['claims'][1] and fits(result,ev,q,CTX)
    assert (report,ev)==before
    invoke.reset_mock()
    assert rewrite_for_beginner(report,ev,q,invoke,json.loads,saved_state=states[-1],publication_context=CTX,**options())==result
    invoke.assert_not_called()


def test_edit_that_fits_raw_limit_but_exceeds_visible_limit_is_rejected():
    report,ev,q=fixture();report['claims']=report['claims'][:1]
    output=answer('字'*100);old_states=[];new_states=[]
    old=rewrite_for_beginner(report,ev,q,Mock(return_value=output),json.loads,contract_version=9,checkpoint=old_states.append)
    assert old_states[-1]['editOutcome']=='applied' and not fits(old,ev,q,CTX)
    new=rewrite_for_beginner(report,ev,q,Mock(return_value=output),json.loads,contract_version=9,publication_context=CTX,checkpoint=new_states.append)
    assert new==report and new_states[-1]['editOutcome']=='rejected'
    assert new_states[-1]['editReason']=='publication_character_limit'


@pytest.mark.parametrize('mutation',['context','budget','version','remove_protocol'])
def test_pending_publication_identity_cannot_change_or_resend(mutation):
    report,ev,q=fixture();states=[]
    rewrite_for_beginner(report,ev,q,Mock(return_value=answer()),json.loads,checkpoint=states.append,publication_context=CTX,**options())
    saved=deepcopy(states[0]);context=deepcopy(CTX)
    if mutation=='context':context['outputKind']='paper_comparison'
    elif mutation=='budget':saved['publicationBudget']['editableCharacters']+=1
    elif mutation=='version':saved['audiencePublicationBudgetContractVersion']=True
    else:context=None
    invoke=Mock()
    with pytest.raises(DeepResearchError,match='保存'):
        rewrite_for_beginner(report,ev,q,invoke,json.loads,saved_state=saved,publication_context=context,**options())
    invoke.assert_not_called()


def test_no_available_rendered_budget_skips_before_provider():
    report,ev,q=fixture();report['claims'][1]['text']='固'*99;states=[];invoke=Mock()
    assert rewrite_for_beginner(report,ev,q,invoke,json.loads,checkpoint=states.append,publication_context=CTX,**options())==report
    assert states[-1]['status']=='skipped' and states[-1]['reason']=='publication_budget_exhausted'
    invoke.assert_not_called()


def test_single_source_reader_uses_same_publication_budget():
    report,ev,q=fixture();report['claims']=report['claims'][:1];states=[]
    rewrite_for_beginner(report,ev,q,Mock(return_value=answer()),json.loads,contract_version=9,
        source_first_single=True,publication_context=CTX,checkpoint=states.append)
    assert states[-1]['editOutcome']=='applied'
    assert 'unverifiedPointHint' not in states[0]['request']['prompt']
    assert states[0]['publicationBudget']['layoutCharacters']>0


@pytest.mark.parametrize('context',[{'outputKind':'claim_verification','presentationVersion':True},
    {'outputKind':'experiment_design','presentationVersion':4}, {'outputKind':'claim_verification','presentationVersion':4,'extra':1}])
def test_publication_context_is_exact(context):
    report,ev,q=fixture()
    with pytest.raises(ValueError):allocation(report,ev,q,context,['fixed'])


def test_profile_is_server_owned_immutable_and_absent_from_legacy(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    key='audiencePublicationBudgetContractVersion'
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'给新手解释，限100字。','deferStart':True,key:False},start_async=False)
        assert type(r[key]) is int and r[key]==1 and enabled(r,r['question'])
        assert not enabled({**r,key:True},r['question'])
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(r['runId'],lambda r:{**r,key:False})
        old=deepcopy(r);old.update(runId='old',idempotencyKey='old');old.pop(key);repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('old',lambda r:{**r,key:1})
    finally:facade.shutdown()
