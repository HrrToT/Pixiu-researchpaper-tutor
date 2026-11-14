from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.repair import _prepare_repair,_parse_repair_response,repair_rejected
from services.deep_research.contracts import DeepResearchError,BudgetExhaustedError
from services.deep_research.verified_text_budget import build,fits,text_count
from services.deep_research.answer_constraints import visible_count
from test_deep_research_verified_text_repair import inputs

CTX={'outputKind':'claim_verification','presentationVersion':4}


def prepare():
    report,verification,ev,opts=inputs()
    return _prepare_repair(report,verification,ev,'解释过程，限100字。',verified_text_edits=True,
        integrated_text_edits=True,text_edit_context=CTX,**opts)


def test_fixed_conditions_siblings_and_publication_labels_all_reserve_space():
    report,verification,ev,_=inputs();report['claims'][0]['conditions']={'setting':'fixed'}
    sibling={**deepcopy(report['claims'][0]),'claimId':'s','text':'已核验的另一个结论。','obligationIds':['o']}
    verification['accepted']=[sibling];report['claims'].append(sibling)
    plan=build(report,verification,ev,'限100字。',{'c':report['claims'][0]},[],(),CTX)
    shadow=deepcopy(report);shadow['claims'][0]['text']=''
    assert plan['budget']['reservedCharacters']==visible_count(shadow,100,CTX['outputKind'],ev,4)
    assert plan['budget']['editableTextCharacters']==100-plan['budget']['reservedCharacters']
    assert plan['budget']['fixedSiblingIds']==['s'] and plan['budget']['includesFixedConditionsAndPublicationLayout']


def test_boundary_budget_is_enforced_before_any_candidate_can_be_verified():
    prepared=prepare();plan=prepared['verifiedTextEditPlan'];maximum=plan['budget']['editableTextCharacters']
    assert 0<maximum<100 and '不要保留旧段落再追加补丁' in prepared['prompt']
    data=json.JSONDecoder().raw_decode(prepared['prompt'].split('Frozen edit inputs (goals, not paper facts):\n',1)[1])[0]
    assert all('currentText' not in t and t['writingResponsibility']['primaryObligationIds'] for t in data['targets'])
    valid=[{'claimId':'c','text':'新'*maximum}]
    assert _parse_repair_response(prepared,{'content':json.dumps(valid)},json.loads,strict_response=True)[0]['text']=='新'*maximum
    with pytest.raises(DeepResearchError):_parse_repair_response(prepared,{'content':json.dumps([{'claimId':'c','text':'新'*(maximum+1)}])},json.loads,strict_response=True)


def test_omitted_verified_target_text_still_occupies_the_shared_budget():
    originals={'a':{'text':'a'*8},'b':{'text':'b'*8}}
    plan={'budget':{'editableTextCharacters':10}}
    assert not fits([{'claimId':'a','text':'x'*3}],originals,plan)
    assert fits([{'claimId':'a','text':'x'*2}],originals,plan)


def test_old_text_protocol_request_is_exact_and_new_settled_request_cannot_switch_budget_policy():
    report,verification,ev,opts=inputs();states=[]
    send=Mock(return_value={'content':json.dumps([{'claimId':'c','text':'新的有据过程解释。'}])})
    base=dict(verified_text_edits=True,**opts);new={**base,'integrated_text_edits':True,'text_edit_context':CTX}
    args=(report,verification,ev,'解释过程，限100字。',send,json.loads)
    result=repair_rejected(*args,checkpoint=states.append,**new)
    assert result and states[-1]['verifiedTextEditAudit']['0']['publicationBudgetChecked']
    assert repair_rejected(*args,batch_state=states[-1],**new)==result
    assert send.call_count==1
    with pytest.raises(DeepResearchError):repair_rejected(*args,batch_state=states[-1],**base)
    assert send.call_count==1


def test_oversized_settled_output_stays_invalid_without_clipping_or_another_send():
    report,verification,ev,opts=inputs();states=[]
    send=Mock(return_value={'content':json.dumps([{'claimId':'c','text':'新'*101}])})
    args=(report,verification,ev,'限100字。',send,json.loads)
    kwargs=dict(verified_text_edits=True,integrated_text_edits=True,text_edit_context=CTX,strict_response=True,**opts)
    assert repair_rejected(*args,checkpoint=states.append,**kwargs)==[]
    assert states[-1]['responseError']['responseState']=='received_invalid'
    assert repair_rejected(*args,batch_state=states[-1],**kwargs)==[] and send.call_count==1


def test_exhausted_fixed_budget_stops_before_a_model_request():
    report,verification,ev,opts=inputs()
    verification['accepted']=[{**deepcopy(report['claims'][0]),'claimId':'s','text':'已'*110}]
    with pytest.raises(BudgetExhaustedError):_prepare_repair(report,verification,ev,'限100字。',verified_text_edits=True,
        integrated_text_edits=True,text_edit_context=CTX,**opts)


def test_missing_explicit_limit_never_invents_a_new_budget():
    report,verification,ev,_=inputs()
    plan=build(report,verification,ev,'解释过程。',{'c':report['claims'][0]},[],(),CTX)
    assert plan['budget'] is None and fits([{'claimId':'c','text':'新'*1000}],{'c':report['claims'][0]},plan)


def test_shared_goals_delegate_detail_to_the_accepted_specific_sibling_without_erasing_assignments():
    c={'claimId':'c','text':'original','conditions':{},'obligationIds':['mechanism','boundary']}
    s={'claimId':'s','text':'fixed','conditions':{},'obligationIds':['boundary']}
    report={'claims':[c,s]};req=[{'obligationId':key} for key in ('mechanism','boundary')]
    plan=build(report,{'accepted':[s]},[],'限100字。',{'c':c},req,(),CTX)
    role=plan['responsibilities'][0]
    assert role['primaryObligationIds']==['mechanism'] and role['detailElsewhere']
    assert c['obligationIds']==['mechanism','boundary']


def test_ambiguous_role_mapping_keeps_original_text_for_localization():
    from services.deep_research.verified_text_repair import integrated_prompt
    originals={'c':{'text':'old contribution','conditions':{},'obligationIds':['o']}}
    plan={'budget':None,'responsibilities':[]}
    prompt=integrated_prompt('question','',[],originals,{'c':{}},{},{},'PERMISSIONS','EVIDENCE',plan)
    data=json.JSONDecoder().raw_decode(prompt.split('Frozen edit inputs (goals, not paper facts):\n',1)[1])[0]
    assert data['targets'][0]['currentText']=='old contribution' and '职责仍需借助旧段落定位' in prompt
