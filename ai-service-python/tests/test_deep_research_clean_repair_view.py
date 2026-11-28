from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.repair import _prepare_repair,_parse_repair_response
from services.deep_research.verification import verify_claims


def packet(policy=9):
    c={'claimId':'c','kind':'reported','text':'失败的旧正文','conditions':{'scope':'旧条件'},
       'evidenceRefs':['e'],'tableBindings':[{'evidenceId':'e','rowNumber':8,'groupIndex':0,'metric':'score','value':'1'}],
       'detailLevel':'fulltext','verification':'semantic_passed','obligationIds':['o']}
    e={'evidenceId':'e','quote':'Table row 8: Ours | 1','sourceWorkId':'paper','sourceVersionId':'v1','contentHash':'h',
       'tableData':{'groups':[['Dataset A',['score']]],'rows':[[8,'Ours',['1']]]},
       'accessLevel':'fulltext','verification':{'literal':'passed'},'obligationIds':['o']}
    report={'claims':[c]};checks={'accepted':[],'rejected':[{'claimId':'c','reason':'answer_incomplete'}]}
    p=_prepare_repair(report,checks,[e],'核查该结果，200字以内',claim_check=policy,fact_redraft=True,source_aware_redraft=True,concise_factual=True,factual_scope=4,compact_source_repair=True)
    return report,checks,e,p


def target(prompt):
    return json.JSONDecoder().raw_decode(prompt.split('Rejected target identities and all checks:\n',1)[1])[0][0]['claim']


def test_only_identity_kind_and_human_obligations_remain_in_new_failed_draft_view():
    report,checks,e,new=packet();*_,old=packet(8);before=deepcopy(report)
    assert target(new['prompt'])=={'claimId':'c','kind':'reported','obligationIds':['o']}
    assert target(old['prompt'])['evidenceRefs']==['E1'] and target(old['prompt'])['tableBindings']
    assert new['originals']==old['originals'] and new['allowed']==old['allowed']
    assert new['originals']['c']['text']=='失败的旧正文' and new['originals']['c']['verification']=='semantic_passed'
    assert json.dumps(e['quote'],ensure_ascii=False) in new['prompt'] and report==before
    assert 'scopeExpression values become published text' in new['prompt']


def test_new_choices_are_checked_not_restored_from_hidden_old_metadata():
    report,checks,e,p=packet()
    row={'claimId':'c','kind':'inference','text':'当前结论仍需核查。','evidenceRefs':['E1'],'conditions':{},
         'tableBindings':[],'draftingBasis':{'scopeDecision':'bounded_inference'}}
    out=_parse_repair_response(p,{'content':json.dumps([row])},json.loads,drafting_audit=[])
    assert out and out[0]['evidenceRefs']==['e'] and out[0]['tableBindings']==[]
    assert out[0].get('verification')!='semantic_passed'
    checker=Mock(return_value=[{'claimId':'c','status':'unresolved','reason':'no approval provided'}])
    assert not verify_claims(out,[e],checker,table_references_version=2)['accepted']
    checker.assert_called_once()
    row['evidenceRefs']=['foreign']
    assert _parse_repair_response(p,{'content':json.dumps([row])},json.loads)==[]


def test_clean_view_does_not_create_sources_or_permissions_when_no_original_anchor_exists():
    report,checks,e,p=packet();report['claims'][0]['evidenceRefs']=[]
    new=_prepare_repair(report,checks,[e],'核查',claim_check=9,fact_redraft=True,source_aware_redraft=True,concise_factual=True,factual_scope=4,compact_source_repair=True)
    assert new['allowed']['c']==[]
    row={'claimId':'c','kind':'reported','text':'声称找到了依据','evidenceRefs':[e['evidenceId']]}
    assert _parse_repair_response(new,{'content':json.dumps([row])},json.loads)==[]
