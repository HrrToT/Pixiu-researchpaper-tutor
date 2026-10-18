from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.audit_source_fields import resolve_target,TARGET_GUIDANCE
from services.deep_research.factual_scope import validate_audit
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.audience_rewrite import _prepare,rewrite_for_beginner,eligible,OUTPUT_TOKENS
from services.deep_research.contracts import DeepResearchError
from services.deep_research.verification import verify_claims
from test_deep_research_audit_source_fields import source
from test_deep_research_audience_rewrite import fixture


def test_target_path_binds_actual_assertion_without_approving_it_as_source_evidence():
    c,e,a=source();a.pop('statementExcerpt');a['statementPath']=['text'];before=deepcopy((c,e,a))
    assert not validate_audit(c,{'scopeAudit':a},[e],source_field_bindings=True,target_field_bindings=True)
    assert validate_audit(c,{'scopeAudit':a},[e],source_field_bindings=True)==['scope_statement_not_bound']
    a['claimStrength']='universal'
    assert validate_audit(c,{'scopeAudit':a},[e],source_field_bindings=True,target_field_bindings=True)==['scope_stronger_than_evidence']
    a['claimStrength']='bounded';a['premises'][0]['evidenceId']='foreign'
    assert validate_audit(c,{'scopeAudit':a},[e],source_field_bindings=True,target_field_bindings=True)==['scope_premises_not_bound']
    assert (c,e)==before[:2] and not verify_claims([c],[e])['accepted']


@pytest.mark.parametrize('path',[['sourceContext'],['claimId'],['text',0],['conditions','missing'],
    ['other','text'],[],None,'text'])
def test_target_binding_never_reads_foreign_metadata_or_invents_a_path(path):
    c,e,a=source();a.pop('statementExcerpt');a['statementPath']=path
    assert resolve_target(a,c) is None
    assert validate_audit(c,{'scopeAudit':a},[e],source_field_bindings=True,target_field_bindings=True)==['scope_statement_not_bound']


def test_target_condition_must_be_an_actual_string_and_cannot_mix_a_paraphrase():
    c,e,a=source();c['conditions']={'scope':'实际范围','number':3};a.pop('statementExcerpt')
    a['statementPath']=['conditions','scope'];assert resolve_target(a,c)=='实际范围'
    a['statementPath']=['conditions','number'];assert resolve_target(a,c) is None
    a['statementPath']=['text'];a['statementExcerpt']='other wording';assert resolve_target(a,c) is None


def test_actual_checker_can_use_both_namespaces_but_the_model_still_decides_support():
    c,e,a=source();a.pop('statementExcerpt');a['statementPath']=['text']
    sent=[]
    def invoke(**kwargs):
        sent.append(kwargs);wire=deepcopy(a);wire['premises']=[{'evidenceId':'E1','path':['quote']}]
        return {'content':json.dumps([{'claimId':'c','status':'failed','reason':'Unsupported reasoning','scopeAudit':wire}])}
    verdict=BudgetedSemanticChecker(invoke,'r',factual_scope=True,audit_source_fields=True,audit_target_fields=True)([c],[e])[0]
    assert verdict['status']=='failed' and TARGET_GUIDANCE in sent[0]['prompt'] and len(sent)==1


def test_source_first_prompt_omits_unverified_prose_and_uses_each_frozen_requested_point():
    report,evidence=fixture();report['claims'][0]['text']='UNVERIFIED_DRAFT_JARGON';report['claims'][0]['conditions']={'x':'UNVERIFIED_CONDITION'}
    requirements=[{'obligationId':'why','question':'解释原因','completionCriteria':[]},
                  {'obligationId':'how','question':'解释过程','completionCriteria':[]}]
    before=deepcopy((report,evidence,requirements))
    new,error=_prepare(report,evidence,'给新手解释原因和过程',contract_version=3,requirement_context=requirements)
    old,_=_prepare(report,evidence,'给新手解释原因和过程',contract_version=2,requirement_context=requirements)
    assert error is None and new['outputTokens']==OUTPUT_TOKENS
    assert 'UNVERIFIED_DRAFT_JARGON' not in new['prompt'] and 'UNVERIFIED_CONDITION' not in new['prompt']
    assert 'UNVERIFIED_DRAFT_JARGON' in old['prompt']
    rows=json.JSONDecoder().raw_decode(new['prompt'].split('Target IDs, original kinds and source permissions (metadata, NOT scientific approval):\n',1)[1])[0]
    assert [r['requestedPoints'] for r in rows]==[[requirements[0]],[requirements[1]]]
    assert all('draftPoint' not in r and 'draftConditions' not in r for r in rows)
    assert evidence[0]['quote'] in new['prompt'] and all(r['evidenceRefs']==['e'] for r in rows)
    assert (report,evidence,requirements)==before
    assert eligible({'audienceRewriteContractVersion':3,'question':'给新手解释'},report,'direction_survey')


def test_source_first_merge_preserves_kind_citations_and_durable_original_without_extra_call():
    report,evidence=fixture();states=[];invoke=Mock(return_value={'content':json.dumps({'claims':[
        {'claimId':c['claimId'],'text':'普通动作解释','conditions':{}} for c in report['claims']]})})
    result=rewrite_for_beginner(report,evidence,'给新手解释',invoke,json.loads,contract_version=3,checkpoint=states.append)
    assert invoke.call_count==1 and states[-1]['originalReport']==report
    assert all(c['kind']==old['kind'] and c['evidenceRefs']==old['evidenceRefs'] and c['obligationIds']==old['obligationIds']
               for c,old in zip(result['claims'],report['claims']))
    assert all(c['text']=='普通动作解释' for c in result['claims'])
    no_dispatch=Mock(side_effect=AssertionError('No second call'))
    assert rewrite_for_beginner(report,evidence,'给新手解释',no_dispatch,json.loads,contract_version=3,saved_state=states[-1])==result
    no_dispatch.assert_not_called()
    assert not verify_claims(result['claims'],evidence)['accepted']


def test_unknown_old_audience_request_cannot_be_retargeted_to_source_first_policy():
    report,evidence=fixture();states=[]
    def unknown(*_):raise OSError('unknown')
    with pytest.raises(OSError):
        rewrite_for_beginner(report,evidence,'给新手解释',unknown,json.loads,contract_version=2,checkpoint=states.append)
    dispatch=Mock()
    with pytest.raises(DeepResearchError,match='不一致'):
        rewrite_for_beginner(report,evidence,'给新手解释',dispatch,json.loads,contract_version=3,saved_state=states[-1])
    dispatch.assert_not_called()


def test_new_wording_still_fails_numeric_checks_and_malformed_target_metadata_is_not_executed():
    report,evidence=fixture();invoke=lambda *_:{'content':json.dumps({'claims':[
        {'claimId':c['claimId'],'text':'999 FPS','conditions':{}} for c in report['claims']]})}
    result=rewrite_for_beginner(report,evidence,'给新手解释',invoke,json.loads,contract_version=3)
    assert verify_claims(result['claims'],evidence)['rejected'][0]['reason']=='numeric_mismatch'
    report['claims'][0]['obligationIds']=[{}]
    request,reason=_prepare(report,evidence,'给新手解释',contract_version=3)
    assert request is None and reason=='invalid_draft'
