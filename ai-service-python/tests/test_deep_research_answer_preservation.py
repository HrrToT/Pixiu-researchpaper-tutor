from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.answer_constraints import compact_answer
from services.deep_research.answer_preservation import GUIDANCE
from services.deep_research.request_semantics import normalize_access_requirements


def report():
    return {'claims':[{'claimId':key,'kind':kind,'text':text*20,'conditions':{},'evidenceRefs':[key+'-source'],
        'obligationIds':[key+'-goal'],'detailLevel':'fulltext'} for key,kind,text in (
        ('overview','reported','概述压缩流程。'),('mechanism','reported','解释如何剪枝与蒸馏。'),
        ('reading','proposal','建议先读方法，再读实验。'))]}


def short(ids=('overview','mechanism','reading')):
    return {'claims':[{'claimId':key,'text':{'overview':'压缩改变表示。','mechanism':'剪枝减少高斯，蒸馏降低SH阶数。','reading':'建议先读方法，再读实验。'}[key],'conditions':{}} for key in ids]}


def test_general_compaction_keeps_reading_deliverable_in_actual_edit_input():
    original=report();before=deepcopy(original)
    invoke=Mock(return_value={'content':json.dumps(short())})
    result=compact_answer(original,'说明方法，给出阅读顺序，300字以内',invoke,json.loads,
        output_kind='direction_survey',presentation_version=4,preserve_answers=True)
    assert result and [c['claimId'] for c in result['claims']]==['overview','mechanism','reading']
    prompt=invoke.call_args.args[0];assert 'reading' in prompt and GUIDANCE in prompt
    for old,new in zip(original['claims'],result['claims']):
        assert {k:v for k,v in old.items() if k not in ('text','conditions')}=={k:v for k,v in new.items() if k not in ('text','conditions')}
    assert original==before


def test_legacy_first_two_selection_is_unchanged():
    invoke=Mock(return_value={'content':json.dumps(short(('overview','mechanism')))})
    result=compact_answer(report(),'300字以内',invoke,json.loads,presentation_version=4)
    assert [c['claimId'] for c in result['claims']]==['overview','mechanism']
    assert 'reading' not in invoke.call_args.args[0]


@pytest.mark.parametrize('change',['drop','reorder','empty','kind','refs','detail_level','extra'])
def test_edit_cannot_drop_required_point_or_mutate_scientific_metadata(change):
    value=short()
    if change=='drop':value['claims'].pop()
    elif change=='reorder':value['claims'].reverse()
    elif change=='empty':value['claims'][-1]['text']=' '
    elif change=='kind':value['claims'][-1]['kind']='reported'
    elif change=='refs':value['claims'][0]['evidenceRefs']=['borrowed']
    elif change=='detail_level':value['claims'][0]['detailLevel']='abstract'
    else:value['claims'][0]['unverified']='new data'
    invoke=Mock(return_value={'content':json.dumps(value)})
    assert compact_answer(report(),'300字以内',invoke,json.loads,presentation_version=4,preserve_answers=True) is None
    invoke.assert_called_once()


@pytest.mark.parametrize('extra',['并给出判断依据','并指出该信息在材料中的体现','并说明该信息在原文中的位置'])
def test_provenance_only_addition_does_not_expand_human_access_request(extra):
    excerpt='标明实际读到的是全文还是摘要'
    plan=[{'obligations':[{'obligationId':'a','question':'是全文还是摘要','purpose':'answer_requirement',
        'requestExcerpt':excerpt,'requiredSources':['p'],'completionCriteria':[
            {'criterionId':'a','responseType':'identification','requirement':'说明依据材料是全文还是摘要，'+extra}]}]}]
    result,changes=normalize_access_requirements(plan,excerpt,version=3)
    assert changes and result[0]['obligations'][0]['completionCriteria'][0]['requirement']==excerpt
    assert normalize_access_requirements(plan,excerpt,version=1)[1]==[]


def test_provenance_projection_cannot_remove_an_extra_scientific_requirement():
    excerpt='标明实际读到的是全文还是摘要'
    plan=[{'obligations':[{'obligationId':'a','question':excerpt,'purpose':'answer_requirement','requestExcerpt':excerpt,
        'completionCriteria':[{'criterionId':'a','responseType':'identification','requirement':excerpt+'并给出实验质量对比的判断依据'}]}]}]
    assert normalize_access_requirements(plan,excerpt,version=3)==(plan,[])


@pytest.mark.parametrize('replacement',[None,True,0,2,'1'])
def test_preservation_contract_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'说明方法与阅读顺序',
            'deferStart':True,'answerPreservationContractVersion':replacement},start_async=False)
        assert run['answerPreservationContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'answerPreservationContractVersion':replacement})
    finally:facade.shutdown()


def test_new_repair_guidance_keeps_source_permissions_and_cannot_reuse_old_batch():
    from services.deep_research.verification import make_evidence
    from services.deep_research.repair import _prepare_repair,repair_rejected
    from services.deep_research.contracts import DeepResearchError
    quote='Pruning removes redundant Gaussians.'
    evidence=make_evidence({'workId':'p','versionId':'v','contentHash':'h','accessLevel':'fulltext'},quote,quote,location={},obligation_ids=[])
    original={'claims':[{'claimId':'c','text':'剪枝减少冗余。','kind':'reported','evidenceRefs':[evidence['evidenceId']]}]}
    checks={'accepted':[],'rejected':[{'claimId':'c','reason':'semantic_unresolved'}]}
    old=_prepare_repair(original,checks,[evidence],'说明方法')
    new=_prepare_repair(original,checks,[evidence],'说明方法',preserve_answers=True)
    assert GUIDANCE in new['prompt'] and old['originals']==new['originals'] and old['allowed']==new['allowed']
    saved=[];invoke=Mock(return_value={'content':'[]'})
    repair_rejected(original,checks,[evidence],'说明方法',invoke,json.loads,checkpoint=lambda s:saved.append(deepcopy(s)))
    invoke.reset_mock()
    with pytest.raises(DeepResearchError):
        repair_rejected(original,checks,[evidence],'说明方法',invoke,json.loads,batch_state=saved[-1],preserve_answers=True)
    invoke.assert_not_called()
