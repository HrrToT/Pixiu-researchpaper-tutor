from copy import deepcopy
import pickle
import pytest

from services.deep_research.answer_constraints import requested_character_limit
from services.deep_research.answer_format import requested_points,publication_format_gaps
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.request_context import effective_question


def record(version=None):
    value={'question':'接着我保存的第二点，解释它为什么可能损失质量。保留原成果，只追加说明，120字以内。',
        'parentRunId':'parent','continuationContextContractVersion':1,'answerFormatContractVersion':1,
        'continuationContext':{'parentRunId':'parent','parentInstructions':['解释剪枝和SH降阶，只写两点，200字以内。'],
            'artifactContext':{'text':'我的第二个问题改为：剪枝为何可能损失细节。只写六点只是原稿中的例子。','accessLevel':'unverified_context'}}}
    if version is not None: value['continuationFormatContractVersion']=version
    return value


def test_new_followup_does_not_inherit_old_point_count_but_keeps_current_limit_and_parent_goal_context():
    old=effective_question(record());new=effective_question(record(1))
    assert requested_points(old)=={'count':2,'mode':'exact'} and requested_points(new) is None
    assert requested_character_limit(old)==requested_character_limit(new)==120
    assert new.instruction_layers==old.instruction_layers and 'UNVERIFIED GOAL CONTEXT' in new
    assert 'Point counts from earlier questions do not apply' in new


def test_current_explicit_point_count_and_latest_human_clarification_still_apply():
    value=record(1);value['question']='接着第二点，解释剪枝损失，最多三点，120字以内。'
    assert requested_points(effective_question(value))=={'count':3,'mode':'max'}
    value.update(clarificationContractVersion=1,state={'clarification':'只写一点。','clarificationHistory':[
        {'question':'要分几条？','answer':'只写一点。'}]})
    assert requested_points(effective_question(value))=={'count':1,'mode':'exact'}


def test_repeating_original_question_retains_its_explicit_count_and_ordinary_runs_are_unchanged():
    value=record(1);value['question']=value['continuationContext']['parentInstructions'][0]
    assert requested_points(effective_question(value))=={'count':2,'mode':'exact'}
    plain={'question':'解释这个机制，只写两点，200字以内。','continuationFormatContractVersion':1}
    assert effective_question(plain)==plain['question']
    assert requested_points(effective_question(plain))=={'count':2,'mode':'exact'}


def test_format_metadata_survives_deepcopy_and_pickle_without_turning_artifact_prose_into_instructions():
    q=effective_question(record(1))
    for restored in (deepcopy(q),pickle.loads(pickle.dumps(q))):
        assert restored==q and restored.instruction_layers==q.instruction_layers
        assert requested_points(restored) is None and requested_character_limit(restored)==120


def test_same_verified_one_point_answer_has_only_old_inherited_format_gap():
    claim={'claimId':'c','text':'简单不透明度剪枝可能误删承载细节的高斯。','kind':'reported','evidenceRefs':['e']}
    sections=[{'title':'判断','claimIds':['c']}]
    old=publication_format_gaps(record(),[claim],sections)
    new=publication_format_gaps(record(1),[claim],sections)
    assert len(old)==1 and old[0]['expectedPointCount']==2 and new==[]
    assert claim['text']=='简单不透明度剪枝可能误删承载细节的高斯。'


@pytest.mark.parametrize('marker',[True,False,0,2,'1'])
def test_unmarked_and_invalid_contracts_keep_legacy_format(marker):
    assert requested_points(effective_question(record(marker)))=={'count':2,'mode':'exact'}


@pytest.mark.parametrize('replacement',[None,True,False,0,2,'1'])
def test_continuation_format_policy_is_owned_and_frozen_by_server(tmp_path,replacement):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        p,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'解释这个变化','deferStart':True,
                         'continuationFormatContractVersion':replacement},start_async=False)
        assert p['continuationFormatContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(p['runId'],lambda r:{**r,'continuationFormatContractVersion':replacement})
    finally: facade.shutdown()
