from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.audience_writing_roles import allocation
from services.deep_research.audience_rewrite import rewrite_for_beginner
from services.deep_research.audience_publication_budget import fits
from services.deep_research.contracts import DeepResearchError
from test_deep_research_audience_edit_budget import fixture,answer
from test_deep_research_audience_publication_budget import CTX


def test_narrow_target_owns_shared_detail_without_changing_frozen_assignments():
    report,_,_=fixture();report['claims'][0]['obligationIds']=['a','b','c','d'];report['claims'][1]['obligationIds']=['d'];original=deepcopy(report)
    result=allocation(report,[{'obligationId':v} for v in 'abcd'],278)
    broad,narrow=result['targets']
    assert broad['primaryObligationIds']==['a','b','c'] and narrow['primaryObligationIds']==['d']
    assert broad['detailElsewhere']==[{'obligationId':'d','claimId':'fixed'}]
    assert sum(t['suggestedTextAndConditionsCharacters'] for t in result['targets'])==278
    assert report==original


def test_identical_roles_stay_shared_and_no_target_can_be_erased():
    report,_,_=fixture();original=deepcopy(report)
    plan=allocation(report,[{'obligationId':'o'}],87)
    assert all(t['primaryObligationIds']==['o'] and not t['detailElsewhere'] for t in plan['targets'])
    assert allocation(report,[{'obligationId':'o'}],87,['fixed']) is None
    report['claims'][0]['obligationIds']=['a','b'];report['claims'][1]['obligationIds']=['a'];report['claims'].append({**deepcopy(report['claims'][1]),'claimId':'third','obligationIds':['b']})
    assert allocation(report,[{'obligationId':v} for v in 'ab'],100) is None
    assert original['claims'][0]['obligationIds']==['o']


def opts():return dict(contract_version=9,mapped_source_first=True,plain_explanations=True,writing_roles=True,publication_context=CTX)


def test_only_valid_but_publication_overlength_edit_is_handed_to_compaction_and_reused():
    report,ev,q=fixture();report['claims']=report['claims'][:1];states=[];invoke=Mock(return_value=answer('新'*100))
    result=rewrite_for_beginner(report,ev,q,invoke,json.loads,checkpoint=states.append,retain_for_compaction=True,**opts())
    assert result['claims'][0]['text']=='新'*100 and not fits(result,ev,q,CTX)
    assert states[-1]['editOutcome']=='compaction_candidate' and states[-1]['editReason']=='publication_character_limit'
    assert states[-1]['audienceMappedSourceContractVersion']==3 and states[-1]['originalReport']==report
    for key in ('claimId','kind','evidenceRefs','obligationIds','tableBindings'):assert result['claims'][0][key]==report['claims'][0][key]
    assert rewrite_for_beginner(report,ev,q,invoke,json.loads,saved_state=states[-1],retain_for_compaction=True,**opts())==result
    assert invoke.call_count==1
    bad=deepcopy(states[-1]);bad['compactionCandidateDigest']='tampered'
    with pytest.raises(DeepResearchError):rewrite_for_beginner(report,ev,q,invoke,json.loads,saved_state=bad,retain_for_compaction=True,**opts())
    with pytest.raises(DeepResearchError):rewrite_for_beginner(report,ev,q,invoke,json.loads,saved_state=states[-1],**opts())
    assert invoke.call_count==1


@pytest.mark.parametrize('mutation',['bad_id','source_permission','raw_overlimit','truncated'])
def test_invalid_edits_never_become_compaction_candidates(mutation):
    report,ev,q=fixture();report['claims']=report['claims'][:1];states=[];response=answer('新'*100)
    if mutation=='bad_id':response['content']=response['content'].replace('edit','foreign')
    elif mutation=='source_permission':
        raw=json.loads(response['content']);raw['claims'][0]['evidenceRefs']=['foreign'];response['content']=json.dumps(raw)
    elif mutation=='raw_overlimit':response=answer('新'*101)
    else:response['finishReason']='length'
    result=rewrite_for_beginner(report,ev,q,Mock(return_value=response),json.loads,checkpoint=states.append,retain_for_compaction=True,**opts())
    assert result==report and states[-1]['editOutcome']=='rejected' and 'compactionCandidateDigest' not in states[-1]


def test_post_compaction_reader_cannot_publish_an_overlength_edit():
    report,ev,q=fixture();report['claims']=report['claims'][:1];states=[]
    assert rewrite_for_beginner(report,ev,q,Mock(return_value=answer('新'*100)),json.loads,checkpoint=states.append,**opts())==report
    assert states[-1]['editOutcome']=='rejected'


def test_actual_synthesis_node_compacts_plain_candidate_once_without_approving_it():
    from services.deep_research.graph import make_synthesize_node
    from test_deep_research_factual_prompt import node_capture
    _,_,record=node_capture(1);record.update(question='给新手解释方法，限100字。',audienceRewriteContractVersion=9,audienceFirstContractVersion=1,audienceMappedSourceContractVersion=3,audiencePublicationBudgetContractVersion=1,reportPresentationContractVersion=4)
    record['state']['outputKind']='claim_verification';events=[]
    def update(rid,fn,**kw):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    def invoke(rid,node,prompt,options,**kw):
        events.append(node)
        if node=='synthesize':return {'content':json.dumps({'sections':[],'claims':[{'claimId':'c','kind':'reported','text':'旧技术草稿。'*35,'evidenceRefs':['E1'],'obligationIds':['o'],'detailLevel':'fulltext','conditions':{}}]})}
        if node=='synthesize_audience':return {'content':json.dumps({'claims':[{'claimId':'c','text':'新'*100,'conditions':{}}]}),'finishReason':'stop'}
        assert node=='synthesize_compact' and '新'*100 in prompt and '旧技术草稿。'*35 not in prompt
        return {'content':json.dumps({'claims':[{'claimId':'c','text':'从观测计算深度，再融合为表面。','conditions':{}}]}),'finishReason':'stop'}
    result=make_synthesize_node(invoke,update)({'run_id':'r'})
    assert 'report_version_id' in result and events==['synthesize','synthesize_audience','synthesize_compact']
    assert record['state']['audienceRewrite']['editOutcome']=='compaction_candidate'
    assert not record['state'].get('verifiedReport')
