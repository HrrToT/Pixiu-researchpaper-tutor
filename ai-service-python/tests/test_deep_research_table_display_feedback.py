from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.repair import repair_rejected
from services.deep_research.verification import verify_claims
from test_deep_research_table_bindings import fixture


def test_rejection_names_the_exact_bound_group_and_variant_without_changing_old_feedback():
    ev,c=fixture();c['text']=c['text'].replace('Ours*','CompressionMethod')
    before=deepcopy([c,ev]);checker=Mock()
    old=verify_claims([c],[ev],checker)
    assert old['rejected']==[{'claimId':'c','reason':'table_condition_not_displayed'}]
    rejection=verify_claims([c],[ev],checker,feedback_version=1)['rejected'][0]
    assert rejection['requiredTableDisplay']==[{'group':'Dataset A','method':'Ours*'}]
    assert '星号' in rejection['detail'] and '单元格' in rejection['detail']
    assert [c,ev]==before
    checker.assert_not_called()


def test_identity_hint_does_not_borrow_an_uncited_row_or_permit_a_wrong_cell():
    ev,c=fixture();c['text']=c['text'].replace('Ours*','CompressionMethod')
    other=deepcopy(ev);other['evidenceId']='foreign';other['tableData']['rows'][0][1]='Different'
    result=verify_claims([c],[ev,other],feedback_version=1)
    assert result['rejected'][0]['requiredTableDisplay']==[{'group':'Dataset A','method':'Ours*'}]
    c['tableBindings'][0]['value']='999'
    assert verify_claims([c],[ev],feedback_version=1)['rejected'][0]=={'claimId':'c','reason':'table_cell_mismatch'}


def test_repair_receives_identity_feedback_and_still_needs_exact_cells_and_semantics():
    ev,valid=fixture();bad={**valid,'text':valid['text'].replace('Ours*','CompressionMethod')}
    rejected=verify_claims([bad],[ev],feedback_version=1)
    def invoke(prompt):
        assert 'requiredTableDisplay' in prompt and 'Ours*' in prompt
        value=deepcopy(valid);value['evidenceRefs']=['E1']
        for binding in value['tableBindings']:binding['evidenceId']='E1'
        return {'content':json.dumps([value])}
    revised=repair_rejected({'claims':[bad]},rejected,[ev],'核查',invoke,json.loads)
    assert not verify_claims(revised,[ev],feedback_version=1)['accepted']
    checker=Mock(return_value=[{'claimId':'c','status':'passed'}])
    assert verify_claims(revised,[ev],checker,feedback_version=1)['accepted']
    checker.assert_called_once()
    revised[0]['tableBindings'][0]['groupIndex']=1
    assert verify_claims(revised,[ev],checker,feedback_version=1)['rejected'][0]['reason']=='table_cell_mismatch'
    assert checker.call_count==1


@pytest.mark.parametrize('replacement',[None,True,'2',0,1,3])
def test_feedback_is_server_owned_frozen_and_forwarded_by_actual_facade(tmp_path,replacement):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'核查','deferStart':True,
            'verificationFeedbackContractVersion':replacement},start_async=False)
        assert run['verificationFeedbackContractVersion']==2
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'verificationFeedbackContractVersion':replacement})
        ev,c=fixture();c['text']=c['text'].replace('Ours*','CompressionMethod')
        result=facade._get_verify_claims(run['runId'])([c],[ev])
        assert result['rejected'][0]['requiredTableDisplay']==[{'group':'Dataset A','method':'Ours*'}]
    finally:facade.shutdown()
