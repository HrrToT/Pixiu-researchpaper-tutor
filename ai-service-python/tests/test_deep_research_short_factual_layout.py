from copy import deepcopy
import hashlib,json
from unittest.mock import Mock
import pytest
from services.deep_research.short_factual_layout import enabled,GUIDANCE,PROSE_GUIDANCE,valid_access_labels
from services.deep_research.factual_template import build
from services.deep_research.answer_constraints import compact_answer


def test_policy_requires_frozen_new_version_short_human_limit_and_factual_check():
    assert enabled({'answerFormatContractVersion':2},'claim_verification',300)
    for v in (None,True,False,0,1,'2',3):assert not enabled({'answerFormatContractVersion':v},'claim_verification',300)
    for kind,limit in [('experiment_design',300),('paper_comparison',300),('claim_verification',None),('claim_verification',301),('claim_verification',True)]:
        assert not enabled({'answerFormatContractVersion':2},kind,limit)


def test_generation_layout_changes_no_scientific_inputs_or_criteria():
    r={'answerFormatContractVersion':2,'state':{'evidence':[]}}
    args=(r,'核查结论，两点300字以内','claim_verification',300,2,['判断','支持证据','反对证据','适用条件','未解决事项'],[{'obligationId':'o','completionCriteria':[{'requirement':'核查结果和边界'}]}],{},'EVIDENCE_SLOT','TABLE_SLOT')
    before=deepcopy(args);p=build(*args)
    assert GUIDANCE in p and 'Suggested section titles: ["核查结论","依据与范围"]' in p
    assert p.count('EVIDENCE_SLOT')==1 and p.count('TABLE_SLOT')==1 and '核查结果和边界' in p
    assert args==before
    old=deepcopy(r);old['answerFormatContractVersion']=1
    assert GUIDANCE not in build(old,*args[1:])


@pytest.mark.parametrize('value',['summary','brief',None,True,[],{}])
def test_access_tag_is_an_enum_not_a_summary_style(value):
    assert not valid_access_labels([{'detailLevel':value}])
    assert valid_access_labels([{'detailLevel':'fulltext'},{'detailLevel':'abstract'}])


def test_compaction_still_rejects_overlength_and_does_not_drop_ids_or_metadata():
    report={'claims':[{'claimId':'a','kind':'inference','text':'原有解释。'*50,'conditions':{},'evidenceRefs':['e'],'detailLevel':'fulltext','obligationIds':['o']} ]}
    before=deepcopy(report);sent=[]
    def invoke(p):sent.append(p);return {'content':json.dumps({'claims':[{'claimId':'a','text':'有界结论。','conditions':{}}]})}
    out=compact_answer(report,'100字以内',invoke,json.loads,preserve_claims=True,explicit_edit_scope=True,compact_layout=True)
    assert out['claims'][0]['text']=='有界结论。' and out['claims'][0]['evidenceRefs']==['e'] and report==before
    assert PROSE_GUIDANCE in sent[0] and '原稿当前可见长度' in sent[0]
    too_long=Mock(return_value={'content':json.dumps({'claims':[{'claimId':'a','text':'不能通过。'*100,'conditions':{}}]})})
    assert compact_answer(report,'100字以内',too_long,json.loads,preserve_claims=True,compact_layout=True) is None
    drop=Mock(return_value={'content':'{"claims":[]}'})
    assert compact_answer(report,'100字以内',drop,json.loads,preserve_claims=True,compact_layout=True) is None


def test_repair_uses_layout_identity_and_never_coerces_an_invalid_access_tag():
    from services.deep_research.repair import repair_rejected
    from services.deep_research.contracts import DeepResearchError
    c={'claimId':'c','kind':'inference','text':'原推断','conditions':{},'evidenceRefs':['e'],'detailLevel':'fulltext','obligationIds':['o']}
    report={'claims':[c]};checks={'accepted':[],'rejected':[{'claimId':'c','reason':'semantic_unresolved'}]};ev=[{'evidenceId':'e','quote':'Observation.','accessLevel':'fulltext'}]
    row={**c,'text':'新有界推断','evidenceRefs':['E1']};invoke=Mock(return_value={'content':json.dumps([row])});states=[]
    out=repair_rejected(report,checks,ev,'核查，300字以内',invoke,json.loads,compact_layout=True,checkpoint=states.append)
    assert out and out[0]['detailLevel']=='fulltext'
    saved=deepcopy(states[-1]);invoke.reset_mock()
    assert repair_rejected(report,checks,ev,'核查，300字以内',invoke,json.loads,compact_layout=True,batch_state=saved)==out
    invoke.assert_not_called()
    with pytest.raises(DeepResearchError):repair_rejected(report,checks,ev,'核查，300字以内',invoke,json.loads,batch_state=saved)
    bad=Mock(return_value={'content':json.dumps([{**row,'detailLevel':'summary'}])})
    assert repair_rejected(report,checks,ev,'核查，300字以内',bad,json.loads,compact_layout=True)==[]


@pytest.mark.parametrize('access',['fulltext','summary'])
def test_generation_passes_layout_to_compaction_and_stops_invalid_access_before_extra_call(access):
    from services.deep_research.graph import make_synthesize_node
    r={'question':'只写一点，80字以内','answerFormatContractVersion':2,'synthesisEvidenceContractVersion':6,'state':{'outputKind':'claim_verification','evidence':[]}}
    original={'sections':[{'title':'核查结论','claimIds':['c']}],'claims':[{'claimId':'c','kind':'inference','text':'原有有界判断。'*50,'conditions':{},'detailLevel':access,'evidenceRefs':[],'obligationIds':[]}]}
    captured=[]
    def update(rid,fn,**kw):
        nonlocal r
        r=fn(deepcopy(r));return deepcopy(r)
    def invoke(rid,node,prompt,options,**kw):
        captured.append((node,prompt))
        return {'content':json.dumps(original if node=='synthesize' else {'claims':[{'claimId':'c','text':'有界判断。','conditions':{}}]})}
    result=make_synthesize_node(invoke,update)({'run_id':'r'})
    assert GUIDANCE in captured[0][1]
    if access=='summary':
        assert result['error_code']=='invalid_synthesis_response' and len(captured)==1
    else:
        assert 'error_code' not in result and len(captured)==2 and PROSE_GUIDANCE in captured[1][1]
        assert r['state']['reportBody']['claims'][0]['detailLevel']=='fulltext'


def test_legacy_factual_wire_remains_byte_identical():
    args=({'answerFormatContractVersion': 1, 'state': {'evidence': []}}, 'question', 'claim_verification', 300, 2, ['判断'], [{'obligationId': 'o'}], {}, 'EVIDENCE', 'TABLE')
    assert hashlib.sha256(build(*args).encode()).hexdigest()=='1eee3c6017ea3b3e888504a757b8c3d6587c974c6ae2ffce7336bed7e635aae3'


@pytest.mark.parametrize('extra',[{'detailLevel':'summary'},{'kind':'reported'},{'evidenceRefs':['foreign']}])
def test_short_compactor_cannot_overwrite_scientific_or_access_metadata(extra):
    c={'claimId':'c','text':'已有判断。'*40,'kind':'inference','conditions':{},'detailLevel':'fulltext','evidenceRefs':['e']}
    invoke=Mock(return_value={'content':json.dumps({'claims':[{'claimId':'c','text':'已有判断。','conditions':{},**extra}]})})
    assert compact_answer({'claims':[c]},'100字以内',invoke,json.loads,compact_layout=True) is None
