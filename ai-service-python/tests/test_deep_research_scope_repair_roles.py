from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.repair import _prepare_repair,_parse_repair_response,repair_rejected
from services.deep_research.scope_expression import materialize
from services.deep_research.contracts import DeepResearchError
from test_deep_research_scope_expression import claim


def packet(required=True):
    raw=claim();original,audit=materialize(raw)
    report={'claims':[original]};checks={'accepted':[],'rejected':[{'claimId':'c','reason':'answer_incomplete'}]}
    evidence=[{'evidenceId':'e','quote':'方法A的剪枝率为66%。','accessLevel':'fulltext'}]
    options={'scope_expression':1,'claim_check':5}
    if required:options['required_scope_ids']=['c']
    return raw,report,checks,evidence,options


@pytest.mark.parametrize('mode',['missing','null','prose'])
def test_scope_repair_cannot_fall_back_to_unchecked_ordinary_prose(mode):
    raw,report,checks,evidence,options=packet();prepared=_prepare_repair(report,checks,evidence,'解释范围',**options)
    before=deepcopy(prepared);row={**raw,'evidenceRefs':['E1'],'text':'未验证范围：其他场景。'}
    if mode=='missing':row.pop('scopeExpression')
    else:row['scopeExpression']=None
    if mode=='prose':row['conditions']={'scope':'所有其他场景未验证'}
    audits=[]
    assert _parse_repair_response(prepared,{'content':json.dumps([row])},json.loads,scope_audit=audits)==[]
    assert audits==[{'claimId':'c','error':'scope_role_downgrade'}] and prepared==before
    assert 'Required scope-role claim IDs: ["c"]' in prepared['prompt']


def test_valid_authored_scope_is_recompiled_and_requires_fresh_scope_review():
    raw,report,checks,evidence,options=packet();prepared=_prepare_repair(report,checks,evidence,'解释范围',**options)
    raw['evidenceRefs']=['E1'];audits=[]
    rows=_parse_repair_response(prepared,{'content':json.dumps([raw])},json.loads,scope_audit=audits)
    assert len(rows)==1 and rows[0]['text']==report['claims'][0]['text']
    assert audits[0]['expression']==raw['scopeExpression'] and audits[0]['verification']=='unchecked'
    assert rows[0].get('verification')!='semantic_passed'


def test_legacy_repair_can_still_return_ordinary_prose():
    raw,report,checks,evidence,options=packet(False);options['claim_check']=4
    prepared=_prepare_repair(report,checks,evidence,'解释范围',**options)
    row={**raw,'scopeExpression':None,'text':'仅当前引用不足以证明推广。','evidenceRefs':['E1']}
    assert len(_parse_repair_response(prepared,{'content':json.dumps([row])},json.loads))==1
    assert 'requiredScopeIds' not in prepared


@pytest.mark.parametrize('ids',[None,'c',['missing'],['c','c'],[True]])
def test_invalid_scope_identity_does_not_reach_dispatch(ids):
    raw,report,checks,evidence,options=packet();options['required_scope_ids']=ids;invoke=Mock()
    with pytest.raises(ValueError,match='required scope'):
        repair_rejected(report,checks,evidence,'解释范围',invoke,json.loads,**options)
    invoke.assert_not_called()


def test_scope_role_and_cache_are_preserved_on_resume_without_resending_bad_reply():
    raw,report,checks,evidence,options=packet();states=[]
    row={**raw,'scopeExpression':None,'text':'未验证其他场景。','evidenceRefs':['E1']}
    invoke=Mock(return_value={'content':json.dumps([row])})
    args=(report,checks,evidence,'解释范围',invoke,json.loads)
    assert repair_rejected(*args,checkpoint=states.append,**options)==[]
    assert states[-1]['scopeExpressionAudit']['0'][0]['error']=='scope_role_downgrade'
    saved=deepcopy(states[-1]);invoke.reset_mock()
    assert repair_rejected(*args,batch_state=saved,**options)==[]
    old={k:v for k,v in options.items() if k!='required_scope_ids'}
    with pytest.raises(DeepResearchError):repair_rejected(*args,batch_state=saved,**old)
    invoke.assert_not_called()


def test_actual_graph_carries_original_scope_identity_into_repair(monkeypatch):
    from services.deep_research.graph import make_verify_node
    raw,report,checks,evidence,options=packet();c=report['claims'][0];_,audit=materialize(raw)
    record={'question':'核查范围','claimCheckContractVersion':5,'scopeExpressionContractVersion':1,
        'state':{'outputKind':'claim_verification','reportBody':report,'evidence':evidence,
                 'synthesisScopeExpressionAudit':[audit],'plan':[]}}
    def update(run,change,**kwargs):
        nonlocal record
        record=change(deepcopy(record));return deepcopy(record)
    repairs=[]
    def repair(*args,**kwargs):repairs.append(kwargs);return []
    monkeypatch.setattr('services.deep_research.repair.repair_rejected',repair)
    monkeypatch.setattr('services.deep_research.final_coverage.audit_final_answer',lambda *a,**kw:{'status':'checked','gaps':[]})
    verify=Mock(return_value=checks)
    make_verify_node(verify,None,update,llm_invoke=lambda *a,**kw:{'content':'[]'})({'run_id':'r'})
    assert len(repairs)==1 and repairs[0]['required_scope_ids']==['c']
    assert repairs[0]['claim_check']==5 and repairs[0]['scope_expression']==1
