from copy import deepcopy
import json
import pytest
from services.deep_research.repair import _prepare_repair, repair_rejected
from services.deep_research.factual_repair import render
from services.deep_research.shared_strings import unpack


def fixture():
    claim={'claimId':'c','kind':'reported','text':'旧的无依据判断。','conditions':{},'evidenceRefs':['e'],'obligationIds':['o']}
    evidence={'evidenceId':'e','sourceWorkId':'work','sourceVersionId':'v1','contentHash':'h','accessLevel':'fulltext',
              'quote':'The method uses a compact representation.','sourceContext':'The method uses a compact representation.',
              'verification':{'literal':'passed'},'location':{'page':2,'offset':0},'obligationIds':['o']}
    requirements=[{'obligationId':'o','question':'解释表示','requiredSources':['work'],
                   'completionCriteria':[{'criterionId':'c','requirement':'解释表示','responseType':'explanation'}]}]
    kwargs={'fact_redraft':True,'source_aware_redraft':True,'concise_factual':True,'compact_source_repair':True,
            'requirement_context':requirements,'scope_expression':4,'table_identity_context':2,'claim_check':9,
            'task_sources':True,'request_semantics':2,'preserve_answers':True,'comparison_methodology':True}
    return {'claims':[claim]},{'accepted':[],'rejected':[{'claimId':'c','reason':'unsupported'}]},[evidence],kwargs


def test_only_prompt_changes_permissions_originals_and_presentation_evidence_stay_exact():
    report,checks,evidence,kwargs=fixture();before=deepcopy((report,checks,evidence,kwargs))
    old=_prepare_repair(report,checks,evidence,'解释表示',**kwargs)
    explicit_old=_prepare_repair(report,checks,evidence,'解释表示',**kwargs,factual_prompt_version=0)
    new=_prepare_repair(report,checks,evidence,'解释表示',**kwargs,factual_prompt_version=1)
    assert old==explicit_old
    assert {k:v for k,v in old.items() if k!='prompt'}=={k:v for k,v in new.items() if k!='prompt'}
    assert len(new['prompt'].encode())<len(old['prompt'].encode())
    assert 'The method uses a compact representation.' in new['prompt']
    assert (report,checks,evidence,kwargs)==before


@pytest.mark.parametrize('bad',[True,'1',4,-1])
def test_invalid_policy_never_silently_uses_new_instructions(bad):
    report,checks,evidence,kwargs=fixture()
    with pytest.raises(ValueError,match='policy'):_prepare_repair(report,checks,evidence,'解释',**kwargs,factual_prompt_version=bad)


def test_prospective_experiment_cannot_use_factual_prompt():
    report,checks,evidence,kwargs=fixture();report['claims'][0].update(kind='proposal',designRole='steps',executionSpec={'x':1})
    with pytest.raises(ValueError,match='factual source-aware'):_prepare_repair(report,checks,evidence,'实验',**kwargs,factual_prompt_version=1)


def test_mixed_facts_and_ordinary_advice_keep_original_kinds():
    report,checks,evidence,kwargs=fixture();advice={**report['claims'][0],'claimId':'a','kind':'proposal','text':'建议先读概述。'}
    report['claims'].append(advice);checks['rejected'].append({'claimId':'a','reason':'unsupported'})
    prepared=_prepare_repair(report,checks,evidence,'解释并建议',**kwargs,ordinary_advice=True,factual_prompt_version=1)
    assert prepared['originals']['a']['kind']=='proposal'
    assert 'ordinary' in prepared['prompt'].lower() and 'experiment' in prepared['prompt']


def test_shared_inputs_decode_all_checks_requirements_and_schema_without_changes():
    repeated='这是一段必须逐字保留的原始研究要求与检查反馈。'*40
    requirements=[{'requirement':repeated}]*4;context={'requiredSources':repeated};questions={'Q1':repeated,'Q2':repeated}
    targets=[{'claimId':'c'}];checks={'c':{'detail':repeated,'additionalChecks':[{'detail':repeated}]}}
    schema={'claimId':'original','text':'actual'}
    prompt=render(question='原始问题',length_contract='500字',requirements=requirements,source_context=context,
        targets=targets,checks=checks,questions=questions,permissions_marker='PERMS',evidence_marker='EVIDENCE',schema=schema,shared_inputs=True)
    lines=prompt.splitlines();packet=next(json.loads(line) for line in lines if line.startswith('{"strings":'))
    assert unpack(packet)=={'requirements':requirements,'source_context':context,'questions':questions,
                           'target_checks':[{'claim':targets[0],'check':checks['c']}],'schema':schema}
    assert '原始问题' in prompt and 'PERMS' in prompt and 'EVIDENCE' in prompt


@pytest.mark.parametrize('replacement',[None,0,True,'1',4])
def test_contract_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'o','question':'比较论文',
                            'factualRepairPromptContractVersion':replacement,'deferStart':True},start_async=False)
        assert run['factualRepairPromptContractVersion']==3
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'factualRepairPromptContractVersion':replacement})
    finally:facade.shutdown()

@pytest.mark.parametrize('new_policy',[1,2,3])
def test_pending_old_request_cannot_switch_prompt_contract_or_be_resent(new_policy):
    from services.deep_research.contracts import DeepResearchError
    from llm.provider import LLMProviderError
    report,checks,evidence,kwargs=fixture();saved=[];sent=[]
    def invoke(*a,**k):
        sent.append(1)
        raise LLMProviderError('unknown',provider='fixture',model='fixture')
    with pytest.raises(LLMProviderError):
        repair_rejected(report,checks,evidence,'解释',invoke,json.loads,**kwargs,
                        checkpoint=lambda value:saved.append(deepcopy(value)))
    assert saved[-1].get('pending') and len(sent)==1
    with pytest.raises(DeepResearchError):
        repair_rejected(report,checks,evidence,'解释',invoke,json.loads,**kwargs,
                        batch_state=saved[-1],factual_prompt_version=new_policy)
    assert len(sent)==1
