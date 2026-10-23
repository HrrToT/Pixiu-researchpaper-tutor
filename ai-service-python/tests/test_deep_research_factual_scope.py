from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.factual_scope import validate_audit
from services.deep_research.tools import BudgetedSemanticChecker


def claim():
    return {'claimId':'c','text':'结果仅适用于设置甲。','kind':'inference','evidenceRefs':['real'], 'conditions':{}}


def evidence():
    return [{'evidenceId':'real','quote':'We observed success at setting A.',
             'sourceContext':'We observed success at setting A. Setting B failed.'}]


def audit(**changes):
    return {'claimStrength':'exclusive','evidenceStrength':'bounded','supported':True,
        'statementExcerpt':'仅适用于设置甲','premises':[{'evidenceId':'real','quote':'We observed success at setting A.'}],**changes}


def test_bounded_observations_cannot_pass_as_exclusive_conditions_even_with_passed_verdict():
    assert validate_audit(claim(),{'scopeAudit':audit()},evidence())==['scope_stronger_than_evidence']
    bounded={**claim(),'text':'当前证据支持在设置甲观察到该结果，不能保证其他设置仍成立。'}
    assert validate_audit(bounded,{'scopeAudit':audit(claimStrength='bounded',statementExcerpt='不能保证其他设置仍成立')},evidence())==[]


@pytest.mark.parametrize('bad',[
    None,{},audit(supported=False),audit(claimStrength='universal'),audit(claimStrength=[]),
    audit(claimStrength='bounded',statementExcerpt='不存在的原话'),
    audit(claimStrength='bounded',premises=[]),
    audit(claimStrength='bounded',premises=[{'evidenceId':'foreign','quote':'We observed success at setting A.'}]),
    audit(claimStrength='bounded',premises=[{'evidenceId':'real','quote':'We proved only A works.'}]),
])
def test_missing_or_unbound_audit_never_approves(bad):
    assert validate_audit(claim(),{'scopeAudit':bad},evidence())


def test_checker_restores_typed_own_ids_and_rejects_stronger_scope_after_received_pass():
    sent=[]
    def invoke(**kwargs):
        sent.append(kwargs)
        row={'claimId':'c','status':'passed','reason':'fixture semantic judgement',
             'scopeAudit':audit(premises=[{'evidenceId':'E1','quote':'We observed success at setting A.'}])}
        return {'content':json.dumps([row]),'finishReason':'stop'}
    checker=BudgetedSemanticChecker(invoke,'r',factual_scope=True)
    result=checker([claim()],evidence())
    assert len(sent)==1 and 'Scope-strength audit' in sent[0]['prompt']
    assert result[0]['status']=='failed' and 'scope_stronger_than_evidence' in result[0]['reason']
    assert result[0]['scopeAudit']['premises'][0]['evidenceId']=='real'
    legacy=BudgetedSemanticChecker(invoke,'r')([claim()],evidence())
    assert legacy[0]['status']=='passed' and 'Scope-strength audit' not in sent[-1]['prompt']


def test_drafting_metadata_is_not_sent_to_independent_verifier():
    row={**claim(),'draftingBasis':{'unresolved':'PRIVATE MODEL ANALYSIS'}}
    sent=[]
    def invoke(**kwargs):
        sent.append(kwargs);return {'content':json.dumps([{'claimId':'c','status':'failed','reason':'unsupported'}])}
    assert BudgetedSemanticChecker(invoke,'r',factual_scope=True)([row],evidence())[0]['status']=='failed'
    assert 'PRIVATE MODEL ANALYSIS' not in sent[0]['prompt']


@pytest.mark.parametrize('replacement',[None,True,False,0,1,'1'])
def test_scope_policy_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        p,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'核查这个结论',
            'deferStart':True,'factualScopeContractVersion':replacement},start_async=False)
        assert p['factualScopeContractVersion']==4
        checker=facade._build_semantic_checker(p['runId'],Mock())
        assert checker._factual_scope() is True
        assert checker._complete_factual_scope() is True
        assert checker._result_attribution() is True
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(p['runId'],lambda r:{**r,'factualScopeContractVersion':replacement})
    finally: facade.shutdown()


def test_synthesis_separates_private_drafting_basis_from_claim_and_report():
    from services.deep_research.graph import make_synthesize_node
    record={'question':'解释范围，200字以内。','factualScopeContractVersion':1,
        'state':{'outputKind':'claim_verification','evidence':[]}}
    def update(_rid,change,**kwargs):
        nonlocal record
        record=change(deepcopy(record));return deepcopy(record)
    basis={'premiseStatus':'not_established','unresolved':'PRIVATE MODEL ANALYSIS'}
    llm=Mock(return_value={'content':json.dumps({'sections':[{'title':'判断','claimIds':['c']}],
        'claims':[{'claimId':'c','text':'证据不足以建立普遍条件。','kind':'inference','evidenceRefs':[],
                   'conditions':{},'draftingBasis':basis}]})})
    make_synthesize_node(llm,update)({'run_id':'r'})
    assert 'fill draftingBasis FIRST' in llm.call_args.args[2]
    assert record['state']['factualDraftingAudit']=={'c':basis}
    assert 'draftingBasis' not in record['state']['reportBody']['claims'][0]


def test_repair_preparation_is_versioned_saved_and_not_repeated_on_resume():
    from services.deep_research.repair import repair_rejected
    report={'claims':[claim()]};checks={'accepted':[],'rejected':[{'claimId':'c','reason':'unsupported scope'}]}
    snapshots=[];prompts=[]
    def invoke(prompt):
        prompts.append(prompt);return {'content':json.dumps([{'claimId':'c','text':'在所列设置观察到结果。',
            'kind':'inference','evidenceRefs':['E1'],'conditions':{},'detailLevel':'fulltext',
            'draftingBasis':{'premiseStatus':'not_established','unresolved':'other settings'}}])}
    kwargs={'fact_redraft':True,'concise_factual':True,'factual_scope':True,
            'checkpoint':lambda s:snapshots.append(deepcopy(s))}
    first=repair_rejected(report,checks,evidence(),'限定范围，200字以内。',invoke,json.loads,**kwargs)
    assert len(prompts)==1 and 'fill draftingBasis FIRST' in prompts[0]
    assert 'draftingBasis' not in first[0] and snapshots[-1]['factualDraftingAudit']['0'][0]['basis']['unresolved']=='other settings'
    assert repair_rejected(report,checks,evidence(),'限定范围，200字以内。',invoke,json.loads,
                           batch_state=snapshots[-1],**kwargs)==first
    assert len(prompts)==1


def test_new_synthesis_cleans_only_own_visible_citation_marker_and_audits_original():
    from services.deep_research.graph import make_synthesize_node
    record={'question':'核查范围，200字以内。','factualScopeContractVersion':1,
        'state':{'outputKind':'claim_verification','evidence':[{
            'evidenceId':'actual','sourceWorkId':'p','quote':'Observed in setting A.',
            'sourceContext':'Observed in setting A.','obligationIds':[]}]}}
    def update(_rid,change,**kwargs):
        nonlocal record
        record=change(deepcopy(record));return deepcopy(record)
    llm=Mock(return_value={'content':json.dumps({'sections':[{'title':'判断','claimIds':['c']}],
        'claims':[{'claimId':'c','text':'在设置甲观察到该结果（E1）。','kind':'reported',
            'evidenceRefs':['E1'],'conditions':{}}]})})
    make_synthesize_node(llm,update)({'run_id':'r'})
    assert record['state']['reportBody']['claims'][0]['text']=='在设置甲观察到该结果。'
    audit=record['state']['synthesisPresentationAudit']['c']
    assert audit and '（E1）' in str(audit)
    assert record['state']['reportBody']['claims'][0]['evidenceRefs']==['actual']


def test_v2_declares_drafting_basis_in_both_actual_generation_schemas_without_changing_v1():
    from services.deep_research.graph import make_synthesize_node
    from services.deep_research.repair import _prepare_repair
    prompts=[]
    for version in (1,2):
        record={'question':'核查范围，200字以内。','factualScopeContractVersion':version,
            'state':{'outputKind':'claim_verification','evidence':[]}}
        def update(_rid,change,**kwargs):
            nonlocal record
            record=change(deepcopy(record));return deepcopy(record)
        llm=Mock(return_value={'finishReason':'length'})
        make_synthesize_node(llm,update)({'run_id':'r'})
        prompts.append(llm.call_args.args[2])
    assert ', draftingBasis (required object' not in prompts[0]
    assert ', draftingBasis (required object' in prompts[1]
    assert 'Required draftingBasis object on EACH output claim' in prompts[1]
    report={'claims':[claim()]};checks={'accepted':[],'rejected':[{'claimId':'c','reason':'unsupported scope'}]}
    old=_prepare_repair(report,checks,evidence(),'200字以内',fact_redraft=True,concise_factual=True,factual_scope=1)
    new=_prepare_repair(report,checks,evidence(),'200字以内',fact_redraft=True,concise_factual=True,factual_scope=2)
    def targets(prompt):
        return json.JSONDecoder().raw_decode(prompt.split('ACTIVE OUTPUT TARGETS FOR THIS REQUEST ONLY:\n',1)[1])[0]
    assert 'draftingBasis' not in targets(old['prompt'])[0]
    assert 'draftingBasis' in targets(new['prompt'])[0]
    assert new['allowed']==old['allowed'] and new['originals']==old['originals']
