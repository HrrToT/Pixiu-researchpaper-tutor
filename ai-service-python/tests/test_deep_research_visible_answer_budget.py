from copy import deepcopy
import json
import re
from unittest.mock import Mock

from services.deep_research.reporting import (build_sections, render_report, publication_notices,
    visible_answer_character_count, source_access_summary)
from services.deep_research.answer_constraints import compact_answer
from services.deep_research.answer_format import publication_format_gaps
from services.deep_research.graph import make_publish_node


def payload(text='已有来源支持的解释。',kind='inference',limit=350):
    claims=[{'claimId':'c','kind':kind,'text':text,'evidenceRefs':['e'],'conditions':{}}]
    visible,folded=publication_notices(claims,presentation_version=2)
    return {'presentationVersion':2,'characterLimit':limit,'outputKind':'direction_survey',
        'claims':claims,'sections':[{'title':'核心判断','claimIds':['c']}],
        'evidence':[{'evidenceId':'e','sourceKind':'arxiv','accessLevel':'fulltext','quote':'Original evidence.'}],
        'limitations':visible,'verificationNotice':folded}


def test_layout_folds_generic_notice_but_preserves_claims_access_conditions_and_quotes():
    value=payload();value['claims'][0]['conditions']={'dataset':'A'};before=deepcopy(value)
    body=render_report(value);main=body.split('<details>',1)[0]
    assert value['claims'][0]['text'] in main and 'dataset：A' in main
    assert source_access_summary(value['claims'],value['evidence']) in main
    assert '推断：' in main and '有依据的推断：' not in main and '## 核心判断' not in main
    assert '推断限于所列证据' not in main and '推断限于所列证据' in body
    assert 'Original evidence.' in body and '#research-evidence-e' in body
    assert value==before


def test_experimental_unverified_notice_is_still_in_the_direct_answer():
    value=payload(kind='hypothesis');body=render_report(value)
    assert '待验证假设：' in body.split('<details>',1)[0]
    assert '尚未经过实验验证' in body.split('<details>',1)[0]


def test_final_count_ignores_only_server_disclosures_and_counts_late_visible_limitations():
    value=payload('甲<details>不能隐藏的事实</details>乙')
    value['limitations']='必须保留的范围限制。'
    count=visible_answer_character_count(value)
    assert count>=len(value['claims'][0]['text'])+len(value['limitations'])
    value['gaps']=[{'question':'缺口'*100}];value['researchNotes']=[{'question':'辅助'*100}]
    value['evidence'][0]['quote']='原文'*10000
    assert visible_answer_character_count(value)==count


def test_existing_neutral_claim_sections_apply_to_new_layout_without_changing_old_records():
    claims=payload()['claims'];proposed=[{'title':'未解决事项','claimIds':['c']}]
    assert build_sections(claims,'claim_verification',proposed,presentation_version=0)[0]['title']=='未解决事项'
    assert build_sections(claims,'claim_verification',proposed,presentation_version=2)==build_sections(
        claims,'claim_verification',proposed,presentation_version=1)


def test_compaction_reserves_layout_cost_even_when_claim_text_fits_and_preserves_input():
    value=payload('甲'*45,limit=55);report={'claims':value['claims'],'sections':value['sections']}
    before=deepcopy(report);old=Mock();assert compact_answer(report,'55字以内',old,json.loads) is report
    old.assert_not_called()
    invoke=Mock(return_value={'content':json.dumps({'claims':[{'claimId':'c','text':'保持来源与适用范围。','conditions':{}}]})})
    result=compact_answer(report,'55字以内',invoke,json.loads,output_kind='direction_survey',
        evidence=value['evidence'],presentation_version=2,preserve_claims=True)
    assert result and result['claims'][0]['evidenceRefs']==['e'] and result['claims'][0]['kind']=='inference'
    sent=invoke.call_args.args[0]
    assert int(re.search(r'总共最多(\d+)字',sent)[1])<55
    assert json.loads(sent.split('输入：',1)[1])[0]['text']=='甲'*45
    assert report==before and invoke.call_count==1
    value['claims']=result['claims'];assert visible_answer_character_count(value)<=55


def test_unshortened_response_cannot_pass_by_ignoring_display_overhead_or_repeat():
    value=payload('甲'*45,limit=55);invoke=Mock(return_value={'content':json.dumps({'claims':value['claims']})})
    assert compact_answer({'claims':value['claims']},'55字以内',invoke,json.loads,
        output_kind='direction_survey',evidence=value['evidence'],presentation_version=2) is None
    assert invoke.call_count==1


def test_final_format_gate_requires_actual_layout_and_counts_it_instead_of_claims_only():
    value=payload('甲'*45,limit=55)
    record={'question':'55字以内','reportPresentationContractVersion':2,'answerFormatContractVersion':1}
    assert publication_format_gaps(record,value['claims'],value['sections'])[0]['stage']=='answer_format'
    gap=publication_format_gaps(record,value['claims'],value['sections'],display_payload=value)[0]
    assert gap['actualCharacterCount']==visible_answer_character_count(value)>55


def test_publication_preserves_overlong_verified_claim_and_marks_partial_without_generation():
    value=payload('甲'*45,limit=55)
    record={'question':'55字以内','reportPresentationContractVersion':2,'answerFormatContractVersion':1,
        'state':{'outputKind':'direction_survey','evidence':value['evidence'],'plan':[],
            'verifiedReport':{'verifiedClaims':value['claims'],'sections':value['sections'],
                              'answerCoverage':{'status':'checked','gaps':[]}}}}
    def update(_id,mutate,**kwargs):
        nonlocal record
        record=mutate(record);return record
    publish=Mock(return_value=({'publicationId':'p'},True))
    make_publish_node(publish,update)({'run_id':'r'})
    result=publish.call_args.kwargs
    assert result['outcome']=='partial' and result['payload']['claims']==value['claims']
    assert any(g.get('stage')=='answer_format' for g in result['payload']['gaps'])
    assert '甲'*45 in result['report_text'] and result['payload']['presentationVersion']==2
    assert '推断限于所列证据' not in result['report_text'].split('<details>',1)[0]


def test_repaired_and_fallback_claims_share_one_heading_without_rewriting_or_loss():
    claims=[{'claimId':'a','text':'已核实的作者报告。'},{'claimId':'b','text':'范围仍有限。'}]
    proposed=[{'title':'判断','claimIds':['a']},{'title':'模型自造标题','claimIds':['b']}]
    before=deepcopy((claims,proposed))
    sections=build_sections(claims,'claim_verification',proposed,presentation_version=2)
    assert sections==[{'title':'判断','claimIds':['a','b']}]
    for version in (0,1):
        assert len(build_sections(claims,'claim_verification',proposed,presentation_version=version))==2
    body=render_report({'presentationVersion':2,'characterLimit':300,'claims':claims,'sections':sections})
    assert '## 判断' not in body and all(c['text'] in body for c in claims)
    assert (claims,proposed)==before


def test_duplicate_retrieval_gaps_display_once_with_all_missing_aspects_and_distinct_reasons():
    gaps=[{'obligationId':'o1','question':'说明范围','missingEvidence':'尚未完整回应','stage':'answer','missingAspects':['成立条件']},
        {'obligationId':'o2','question':'说明范围','missingEvidence':'尚未完整回应','stage':'answer','missingAspects':['未验证范围']},
        {'obligationId':'o3','question':'说明范围','missingEvidence':'原文取得失败','stage':'source'},
        {'obligationId':'scope','question':'整个问题','wholeQuestion':True}]
    value={'presentationVersion':2,'claims':[],'gaps':gaps};before=deepcopy(value)
    body=render_report(value)
    assert '<summary>还有 2 项未完成</summary>' in body
    assert body.count('- 说明范围')==2 and '缺少：成立条件、未验证范围' in body
    assert '原文取得失败' in body and value==before
    value['presentationVersion']=1
    assert '<summary>还有 3 项未完成</summary>' in render_report(value)
