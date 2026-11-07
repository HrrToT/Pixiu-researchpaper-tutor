from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.citation_presentation import normalize
from services.deep_research.contracts import DeepResearchError,UnknownCallError
from services.deep_research.repair import repair_rejected,_prepare_repair,_parse_repair_response
from services.deep_research.verification import verify_claims
from test_deep_research_factual_redraft import inputs


@pytest.mark.parametrize('marker',['(E1)','（E1）','[E1]','（E1、E2）','[E1, E2]'])
def test_known_own_bracketed_markers_are_presentation_only_and_raw_claim_is_unchanged(marker):
    claim={'claimId':'c','kind':'inference','text':'这些条件尚未对齐'+marker+'，不能据此推断固有提速。',
           'conditions':{'scope':['当前证据'+marker]},'evidenceRefs':['a','b']}
    before=deepcopy(claim)
    result,audit=normalize(claim,{'E1':'a','E2':'b'},{'E1':'A reports its setup.','E2':'B reports another benchmark.'})
    assert result['text']=='这些条件尚未对齐，不能据此推断固有提速。'
    assert result['conditions']=={'scope':['当前证据']}
    assert result['evidenceRefs']==claim['evidenceRefs'] and result['kind']==claim['kind']
    assert audit['originalText']==claim['text'] and len(audit['removed'])==2 and claim==before


@pytest.mark.parametrize('text',[
    '证据E1指出设置相同。','P1使用某平台。','结论（E2）','结论（E99）','结论（E1/E2）',
    '结论（E1说明了设置）','结论（E1, 30 FPS）','`(E1)`','```\n(E1)\n```',
    '公式 $(E1)$','x=(E1)','f(E1)','x + (E1)','结论(E1]',
])
def test_ambiguous_uncited_unknown_math_code_or_substantive_parentheses_stay_unchanged(text):
    claim={'claimId':'c','text':text,'evidenceRefs':['a']}
    result,audit=normalize(claim,{'E1':'a','E2':'b'},{'E1':'An actual setup.','E2':'Another setup.'})
    assert result==claim and audit is None


def test_source_symbol_in_quote_or_context_is_not_erased():
    claim={'claimId':'c','text':'该能量（E1）来自原公式。','evidenceRefs':['a']}
    result,audit=normalize(claim,{'E1':'a'},{'E1':'The original paper defines E1 as an energy.'})
    assert result==claim and audit is None


def execute(invoke,**kwargs):
    c,e,check,requirements=inputs()
    return repair_rejected({'claims':[c]},check,[e],'解释网络预测的变化，200字以内',invoke,json.loads,
        fact_redraft=True,source_aware_redraft=True,concise_factual=True,requirement_context=requirements,**kwargs)


def test_factual_prompt_omits_experiment_scaffolding_but_keeps_exact_checks_quotes_context_and_requirements():
    c,e,check,requirements=inputs();captured=[];states=[]
    def invoke(prompt):
        captured.append(prompt)
        assert prompt.startswith('Rebuild ONLY these rejected factual answer targets')
        assert c['text'] not in prompt and c['conditions']['scope'] not in prompt
        assert e['quote'] in prompt and check['rejected'][0]['detail'] in prompt
        assert requirements[0]['completionCriteria'][0]['requirement'] in prompt
        assert 'Accepted experimental definitions' not in prompt and 'seed/split' not in prompt
        assert 'alignment not established' in prompt and 'does NOT establish different conditions' in prompt
        return {'content':json.dumps([{'claimId':'c','kind':'reported','text':'网络预测平移和旋转（E1）。',
            'conditions':{},'evidenceRefs':['E1'],'detailLevel':'fulltext'}])}
    rows=execute(invoke,checkpoint=lambda v:states.append(deepcopy(v)))
    assert len(captured)==1 and rows[0]['text']=='网络预测平移和旋转。'
    assert rows[0]['evidenceRefs']==c['evidenceRefs'] and 'citationPresentationAudit' not in rows[0]
    final=states[-1]
    assert final['citationPresentationAudit']['0'][0]['originalText']=='网络预测平移和旋转（E1）。'
    prepared=next(v['pending']['request']['prepared'] for v in states if v.get('pending'))
    assert prepared['originals']['c']==c
    assert not verify_claims(rows,[e])['accepted']
    semantic=Mock(return_value=[{'claimId':'c','status':'failed','reason':'Fixture rejects unsupported interpretation'}])
    assert not verify_claims(rows,[e],semantic)['accepted'];semantic.assert_called_once()


@pytest.mark.parametrize('text',['作者未提供任何实验（E1）。','实测速度为999 fps（E1）。'])
def test_presentation_cleanup_does_not_fix_absence_or_invented_measurement(text):
    c,e,check,requirements=inputs()
    prepared=_prepare_repair({'claims':[c]},check,[e],'解释',fact_redraft=True,source_aware_redraft=True,
        concise_factual=True,requirement_context=requirements)
    result=_parse_repair_response(prepared,{'content':json.dumps([{'claimId':'c','kind':c['kind'],'text':text,
        'evidenceRefs':['E1'],'conditions':{},'detailLevel':'fulltext'}])},json.loads)
    assert result and '（E1）' not in result[0]['text']
    assert not verify_claims(result,[e])['accepted']


def test_prior_contract_keeps_exact_prompt_and_does_not_normalize_markers():
    c,e,check,requirements=inputs()
    prepared=_prepare_repair({'claims':[c]},check,[e],'解释',fact_redraft=True,source_aware_redraft=True,
        requirement_context=requirements)
    assert 'presentationVersion' not in prepared and 'Revise only the targets' in prepared['prompt']
    result=_parse_repair_response(prepared,{'content':json.dumps([{'claimId':'c','kind':c['kind'],
        'text':'预测平移和旋转（E1）。','evidenceRefs':['E1']}])},json.loads)
    assert result[0]['text'].endswith('（E1）。')


def test_prospective_claims_keep_full_design_prompt_even_with_new_factual_policy():
    c,e,check,requirements=inputs();c['kind']='proposal'
    prepared=_prepare_repair({'claims':[c]},check,[e],'设计',fact_redraft=True,source_aware_redraft=True,
        concise_factual=True,requirement_context=requirements)
    assert c['text'] in prepared['prompt'] and 'presentationVersion' not in prepared
    assert not prepared['prompt'].startswith('Rebuild ONLY')


def test_settled_normalized_drafts_are_reused_without_call_or_audit_change():
    states=[]
    def invoke(prompt):
        return {'content':json.dumps([{'claimId':'c','kind':'reported','text':'预测平移和旋转（E1）。',
            'evidenceRefs':['E1']}])}
    rows=execute(invoke,checkpoint=lambda v:states.append(deepcopy(v)))
    saved=deepcopy(states[-1])
    again=execute(lambda *_:pytest.fail('No settled response regeneration'),batch_state=saved)
    assert again==rows and saved==states[-1]


def test_unknown_keeps_frozen_request_and_version_change_cannot_bypass_it(tmp_path):
    from llm.provider import LLMProviderError
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.tools import TrackedLLMInvoker
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();repo.create_run({'runId':'r','taskId':'t'});repo.begin_execution('r')
    provider=Mock();provider.invoke.side_effect=LLMProviderError('unknown',provider='fixture',model='fixture')
    tracked=TrackedLLMInvoker(provider,repo.reserve_call,repo.complete_call)
    states=[];invoke=lambda prompt:tracked('r','repair_claims',prompt,{'max_tokens':1000})
    with pytest.raises(LLMProviderError): execute(invoke,checkpoint=lambda v:states.append(deepcopy(v)))
    pending=deepcopy(states[-1])
    with pytest.raises(UnknownCallError): execute(invoke,batch_state=pending)
    c,e,check,requirements=inputs()
    with pytest.raises(DeepResearchError,match='保存的修订计划'):
        repair_rejected({'claims':[c]},check,[e],'解释网络预测的变化，200字以内',invoke,json.loads,
            fact_redraft=True,source_aware_redraft=True,requirement_context=requirements,batch_state=pending)
    assert provider.invoke.call_count==1 and pending==states[-1]


@pytest.mark.parametrize('version',[2,3])
def test_actual_verification_node_routes_only_new_factual_contract_to_compact_prompt(version,monkeypatch):
    from services.deep_research.graph import make_verify_node
    c,e,check,requirements=inputs()
    record={'factRedraftContractVersion':version,'state':{'reportBody':{'claims':[c]},'evidence':[e],
            'plan':[{'itemId':'i','obligations':requirements}]}}
    def update(run,change,**kwargs):
        nonlocal record
        record=change(deepcopy(record));return deepcopy(record)
    monkeypatch.setattr('services.deep_research.final_coverage.audit_final_answer',lambda *a,**kw:{'status':'not_requested','gaps':[]})
    prompts=[]
    def invoke(run,node,prompt,options):
        assert node=='repair_claims'
        assert prompt.startswith('Rebuild ONLY') is (version==3)
        assert e['quote'] in prompt and c['text'] not in prompt
        prompts.append(prompt);return {'content':'[]'}
    make_verify_node(Mock(return_value=check),None,update,llm_invoke=invoke)({'run_id':'r'})
    assert len(prompts)==1 and record['state']['repairReport']['claims'][0]==c
    assert not record['state']['verifiedReport']['verifiedClaims']
