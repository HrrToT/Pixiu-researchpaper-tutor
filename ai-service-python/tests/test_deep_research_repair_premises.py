from copy import deepcopy
import pytest
from services.deep_research.repair_premises import required_premises
from services.deep_research.repair import _prepare_repair
from services.deep_research.contracts import BudgetExhaustedError


def fixture():
    evidence=[]
    for work in ('a','b'):
        for i in range(6):
            quote=('This is a substantive description of the method representation and implementation. '*28)+str(i)
            evidence.append({'evidenceId':work+str(i),'sourceWorkId':work,'sourceVersionId':work+'-v1',
                'ownerMaterialId':work,'contentHash':'hash-'+work,'accessLevel':'fulltext','quote':quote,
                'sourceContext':quote,'location':{'page':i+1,'offset':0},'obligationIds':['o'],
                'verification':{'literal':'passed'}})
    claim={'claimId':'c','kind':'inference','text':'未经支持的原始判断。','conditions':{},
           'evidenceRefs':[e['evidenceId'] for e in evidence],'obligationIds':['o']}
    requirements=[{'obligationId':'o','question':'这些片段能否比较显存用量','requiredSources':['a-v1','b-v1'],
        'completionCriteria':[{'criterionId':'q','requirement':'显存证据不足就说明无法比较','responseType':'limitation'}]}]
    return claim,evidence,requirements


def test_broad_unverified_refs_are_hints_each_permitted_version_keeps_an_anchor():
    claim,evidence,req=fixture();before=deepcopy((claim,evidence,req));allowed={'c':claim['evidenceRefs']}
    ids,audit=required_premises([claim],evidence,allowed,req)
    assert len(ids)==2
    assert {e['sourceVersionId'] for e in evidence if e['evidenceId'] in ids}=={'a-v1','b-v1'}
    assert ids<=set(allowed['c']) and audit['targets'][0]['originalEvidenceIds']==claim['evidenceRefs']
    assert audit['verification']=='unchecked_navigation' and (claim,evidence,req)==before


@pytest.mark.parametrize('mutation',['version','literal','permission','duplicate'])
def test_ineligible_candidates_cannot_become_required(mutation):
    claim,evidence,req=fixture();bad=deepcopy(evidence[0]);bad['evidenceId']='bad'
    if mutation=='version':bad['sourceVersionId']='a-v2'
    elif mutation=='literal':bad['verification']['literal']='unchecked'
    extras=[bad,bad] if mutation=='duplicate' else [bad]
    allowed={'c':claim['evidenceRefs']+([] if mutation=='permission' else ['bad'])}
    ids,_=required_premises([claim],[*extras,*evidence],allowed,req)
    assert 'bad' not in ids


def test_unbound_target_retains_legacy_original_source_protection():
    claim,evidence,req=fixture();claim['obligationIds']=[]
    ids,audit=required_premises([claim],evidence,{'c':claim['evidenceRefs']},req)
    assert ids==set(claim['evidenceRefs']) and audit['targets'][0]['mode']=='legacy_unbound'


def test_actual_preparation_fits_broad_draft_without_erasing_original_or_expanding_permissions():
    claim,evidence,req=fixture();report={'claims':[claim]};check={'accepted':[],'rejected':[{'claimId':'c','reason':'unsupported'}]}
    kwargs={'fact_redraft':True,'source_aware_redraft':True,'concise_factual':True,'compact_source_repair':True,
            'requirement_context':req,'claim_check':9}
    before=deepcopy((report,check,evidence))
    with pytest.raises(BudgetExhaustedError):
        _prepare_repair(report,check,evidence,'比较显存',**kwargs,factual_prompt_version=1)
    prepared=_prepare_repair(report,check,evidence,'比较显存',**kwargs,factual_prompt_version=2)
    assert len(prepared['prompt'].encode('utf8'))<=24000
    assert prepared['originals']['c']==claim
    assert set(prepared['allowed']['c'])<=set(claim['evidenceRefs'])
    assert {e['sourceVersionId'] for e in evidence if e['evidenceId'] in prepared['allowed']['c']}=={'a-v1','b-v1'}
    assert prepared['repairPremiseAudit']['targets'][0]['originalEvidenceIds']==claim['evidenceRefs']
    assert (report,check,evidence)==before


def test_previously_verified_target_retains_all_original_citations():
    claim,evidence,req=fixture()
    ids,audit=required_premises([claim],evidence,{'c':claim['evidenceRefs']},req,verified_target_ids=['c'])
    assert ids==set(claim['evidenceRefs'])
    assert audit['targets'][0]['mode']=='verified_citations'
