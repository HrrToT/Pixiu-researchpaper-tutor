from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.extraction_priority import prioritize_extraction_passages, _requested_operation_score
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.extraction import make_batched_extract_node
from services.deep_research.verification import make_evidence
from test_deep_research_extraction_priority import passage


def targets():
    return {
        'output':{'obligationId':'output','question':'What does the predictor output?',
            'searchQuery':'predictor Gaussian parameter changes','requiredSources':['a'],
            'completionCriteria':[{'responseType':'identification'}]},
        'state':{'obligationId':'state','question':'How does it use the previous frame representation?',
            'searchQuery':'predictor previous frame representation','requiredSources':['a'],
            'completionCriteria':[{'responseType':'explanation'}]},
        'reason':{'obligationId':'reason','question':'Why add primitives for emerging objects?',
            'searchQuery':'primitive addition reason','requiredSources':['a'],
            'completionCriteria':[{'responseType':'explanation'}]}}


def corpus():
    benchmark=passage('implementation','a','The predictor is implemented with Gaussian parameters. '
        'The predictor learns changes for each frame and improves prediction accuracy.')
    definition=passage('definition','a','The network maps its encoding to an output vector. '
        'Its components represent translation and rotation.')
    transfer=passage('transfer','a','For subsequent steps, previous primitives are used as initialization '
        'and passed to a transformation stage. The transformed primitives are carried to the next step.')
    reason=passage('reason','a','Since old primitives cannot represent emerging objects, adding new primitives is necessary.')
    return [benchmark,definition,transfer,reason]


def test_output_and_previous_state_operations_get_separate_first_batch_slots():
    rows=corpus();before=deepcopy(rows)
    new=prioritize_extraction_passages(rows,targets(),4)
    assert [r[0]['sourceId'] for r in new[:3]]==['definition','transfer','reason']
    assert new!=prioritize_extraction_passages(rows,targets(),3)
    assert rows==before and sorted(r[0]['sourceId'] for r in new)==sorted(r[0]['sourceId'] for r in rows)


def test_temporal_words_without_an_operation_or_in_a_separate_sentence_get_no_bonus():
    for text in ['A previous frame is mentioned. A renderer is described.',
                 'Previous frames are stored on disk.',
                 'A model transforms parameters.']:
        assert _requested_operation_score(text,temporal=True)==0
    rows=corpus();obs=targets();obs['state']['question']='How does the model represent space?'
    assert prioritize_extraction_passages(rows,obs,4)!=prioritize_extraction_passages(rows,targets(),4)


def test_literal_measurements_paper_balance_and_scope_are_not_lost_to_operation_ranking():
    rows=corpus();extra=passage('exact','a','The requested operation takes 17 seconds.')
    rows.append(extra);obs=targets();obs['output']['question']='What does the predictor output in 17 seconds?'
    new=prioritize_extraction_passages(rows,obs,4)
    assert new[0][0]['sourceId']=='exact'
    other=passage('b','b','A separate authorized source with its own description.')
    foreign=passage('foreign','x','The network outputs translations. It passes previous states to the next step.')
    obs=targets()
    for o in obs.values():o['requiredSources']=['a','b']
    new=prioritize_extraction_passages([foreign,*corpus(),other],obs,4)
    assert {r[0]['workId'] for r in new[:2]}=={'a','b'} and new[-1][0]['sourceId']=='foreign'


def test_actual_extraction_node_uses_new_order_without_granting_semantic_approval(tmp_path):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    reads=[{**source,'contentHash':'hash','pages':[{'text':text,**location}]} for source,location,text in corpus()]
    repo.create_run({'runId':'r','taskId':'t','extractionPriorityVersion':4,
        'adaptiveExtractionContractVersion':1,'adaptiveResearchContractVersion':1,
        'state':{'readResults':reads,'plan':[{'itemId':'i','obligations':list(targets().values())}]}})
    repo.begin_execution('r');invoke=Mock(return_value={'content':'[]'})
    make_batched_extract_node(invoke,make_evidence,lambda *a:True,repo.update_run)({'run_id':'r'})
    import json
    prompt=invoke.call_args.args[2]
    values=json.loads(prompt[prompt.index('[{'):])
    assert [v['sourceId'] for v in values]==['definition','transfer','reason']
    assert [v['passageId'] for v in values]==['X1','X2','X3']
    assert repo.require_run('r')['state']['evidence']==[] and invoke.call_count==1


@pytest.mark.parametrize('replacement',[None,True,'4',0,1,2,3,4,5,8])
def test_new_priority_is_server_owned_and_frozen(tmp_path,replacement):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain the mechanism',
            'extractionPriorityVersion':replacement,'deferStart':True},start_async=False)
        assert run['extractionPriorityVersion']==7
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'extractionPriorityVersion':replacement})
    finally:facade.shutdown()
