from copy import deepcopy
import json
import pytest
from services.deep_research.factual_prompt import build
from services.deep_research.repair import _prepare_repair,repair_rejected
from services.deep_research.verification import verify_claims
from test_deep_research_factual_repair_instructions import fixture


def test_new_synthesis_distinguishes_plain_quotations_and_source_local_cells():
    from test_deep_research_factual_prompt import template
    old=template({'factualPromptContractVersion':2})
    new=template({'factualPromptContractVersion':3})
    assert 'Table quantities require tableBindings:' in old
    assert 'Plain-text tables' in new and 'tableBindings=[]' in new
    assert 'original source rowNumber' in new and 'zero-based groupIndex' in new
    assert 'own literal quotation' in new and 'Independent checks remain' in new
    assert 'Omit unsupported optional' in new


def test_plain_quote_numeric_fact_still_requires_exact_number_and_independent_review():
    evidence={'evidenceId':'e','sourceWorkId':'a','sourceVersionId':'a-v1','contentHash':'h','accessLevel':'fulltext',
        'quote':'Method A on Dataset Q reports PSNR 27.3.','verification':{'literal':'passed'}}
    claim={'claimId':'c','kind':'reported','text':'Method A on Dataset Q reports PSNR 27.3.',
           'conditions':{},'evidenceRefs':['e'],'tableBindings':[]}
    checked=[]
    def semantic(claims,rows):
        checked.extend(claims)
        return [{'claimId':c['claimId'],'status':'passed'} for c in claims]
    assert verify_claims([claim],[evidence],semantic)['accepted'] and checked
    wrong={**claim,'text':claim['text'].replace('27.3','28.1')}
    assert verify_claims([wrong],[evidence],semantic)['rejected'][0]['reason']=='numeric_mismatch'
    invented={**claim,'tableBindings':[{'evidenceId':'e','rowNumber':1,'groupIndex':0,'metric':'PSNR','value':'27.3'}]}
    assert verify_claims([invented],[evidence],semantic)['rejected'][0]['reason']=='table_binding_outside_citation'
    assert not verify_claims([claim],[evidence],None)['accepted']


def test_clean_comparison_repair_hides_rejected_cells_but_keeps_original_audit():
    report,checks,evidence,kwargs=fixture();kwargs['claim_check']=False
    binding={'evidenceId':'e','rowNumber':999,'groupIndex':0,'metric':'UNVERIFIED_ROW_TOKEN','value':'999.7'}
    report['claims'][0]['tableBindings']=[binding];before=deepcopy(report)
    old=_prepare_repair(report,checks,evidence,'解释',**kwargs,factual_prompt_version=2)
    new=_prepare_repair(report,checks,evidence,'解释',**kwargs,factual_prompt_version=3)
    assert 'UNVERIFIED_ROW_TOKEN' in old['prompt']
    assert 'UNVERIFIED_ROW_TOKEN' not in new['prompt']
    assert new['originals']==old['originals'] and report==before
    assert new['allowed']==old['allowed']
    assert 'tableBindings=[]' in new['prompt']
    assert '"rowNumber":"actual integer"' in old['prompt']
    assert '"rowNumber":"actual integer"' not in new['prompt']


@pytest.mark.parametrize('old_policy',[0,1,2])
def test_pending_prior_request_cannot_switch_to_clean_repair(old_policy):
    from services.deep_research.contracts import DeepResearchError
    from llm.provider import LLMProviderError
    report,checks,evidence,kwargs=fixture();sent=[];saved=[]
    def invoke(*a,**k):
        sent.append(1);raise LLMProviderError('unknown',provider='fixture',model='fixture')
    with pytest.raises(LLMProviderError):
        repair_rejected(report,checks,evidence,'解释',invoke,json.loads,**kwargs,factual_prompt_version=old_policy,
                        checkpoint=lambda x:saved.append(deepcopy(x)))
    with pytest.raises(DeepResearchError):
        repair_rejected(report,checks,evidence,'解释',invoke,json.loads,**kwargs,factual_prompt_version=3,batch_state=saved[-1])
    assert len(sent)==1


def test_actual_visible_typed_packet_keeps_the_typed_output_schema():
    report,checks,evidence,kwargs=fixture();kwargs['claim_check']=False
    evidence[0]['quote']='Table row 3: Method A | 27.3'
    evidence[0]['sourceContext']=evidence[0]['quote']
    evidence[0]['tableData']={'groups':[['Dataset Q',['PSNR']]],'rows':[[3,'Method A',['27.3']]]}
    prepared=_prepare_repair(report,checks,evidence,'解释',**kwargs,factual_prompt_version=3)
    assert '"rowNumber":"actual integer"' in prepared['prompt']
    assert 'source rowNumber' in prepared['prompt']
