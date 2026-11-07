from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.experiment_edits import columnar,restore_columns,can_edit,expand,OUTPUT_TOKENS
from services.deep_research.repair import _prepare_repair,_parse_repair_response,repair_rejected
from services.deep_research.execution_materialization import materialize_execution_claim,verification_claim_view
from services.deep_research.contracts import DeepResearchError
from services.deep_research.verification import verify_claims
from test_deep_research_shared_experiment_repair import inputs


def prepare():
    report,checks,evidence=inputs()
    return _prepare_repair(report,checks,evidence,'Two groups with and without one whole stage.',
        experimental_intent=3,shared_experiment_schema=True,experimental_edits=True)


def decode(prompt,label):
    return json.JSONDecoder().raw_decode(prompt.split(label,1)[1].lstrip())[0]


@pytest.mark.parametrize('rows',[[],[{}],[{'a':None},{'b':0}],
    [{'id':'a','same':False,'nested':{'values':[1,None,'中文']}},{'id':'b','same':0,'extra':{}}]])
def test_column_tables_preserve_every_field_value_null_and_absence(rows):
    before=deepcopy(rows);packed=columnar(rows)
    assert restore_columns(packed)==rows==before
    if packed:
        packed['rows'][0][-1]['new']='isolated'
        assert rows==before


def test_prompt_retains_complete_originals_checks_and_source_data_as_lossless_tables():
    report,checks,evidence=inputs();before=deepcopy((report,checks,evidence));p=prepare()
    targets=restore_columns(decode(p['prompt'],'Writable original claims:'))
    rejection=restore_columns(decode(p['prompt'],'ALL rejection checks:'))
    rows=restore_columns(decode(p['prompt'],'Exact original evidence/context/table data (lossless column table):'))
    assert 'Check prose may use former E labels' in p['prompt']
    assert {r['claimId'] for r in targets}=={r['claimId'] for r in report['claims']}
    for original,target in zip(report['claims'],targets):
        assert target['text']==verification_claim_view(original)['text']
        assert target.get('executionSpec')==original.get('executionSpec')
        assert target.get('conditions',{})==original.get('conditions',{})
    assert all(r.get('additionalChecks') for r in rejection)
    assert any(row['quote']==evidence[0]['quote'] for row in rows)
    assert p['originals']=={c['claimId']:c for c in report['claims']} and p['editFormatVersion']==1
    assert (report,checks,evidence)==before


def test_edits_reconstruct_full_claims_and_preserve_original_kind_role_and_scope():
    p=prepare();before=deepcopy(p)
    patch=[{'claimId':'budget','edits':[{'op':'replace','path':'/text','value':'Proposed unequal whole-stage budget.'},
        {'op':'replace','path':'/executionSpec/recovery/mode','value':'unmatched'},
        {'op':'add','path':'/executionSpec/recovery/note','value':'Whole-stage extra optimization is measured as cost.'}]}]
    result=_parse_repair_response(p,{'content':json.dumps(patch)},json.loads,strict_response=True)
    assert len(result)==1
    c=result[0];original=p['originals']['budget']
    for key in ('claimId','kind','designRole','designContractVersion','budgetContractVersion','obligationIds','evidenceRefs'):
        assert c[key]==original[key]
    assert c['executionSpec']['baseline']==original['executionSpec']['baseline']
    assert c['executionSpec']['recovery']['mode']=='unmatched'
    assert 'verification' not in c and p==before


@pytest.mark.parametrize('path',['/claimId','/kind','/designRole','/designContractVersion','/workflowContractVersion',
    '/otherClaim/text','', '/', '/text/0', '/conditions/bad~2escape', '/evidenceRefs/01', '/evidenceRefs/-',
    '/evidenceRefs/99999','/executionSpec/no/such/path'])
def test_invalid_or_immutable_pointer_never_mutates_a_claim(path):
    p=prepare();before=deepcopy(p)
    result=expand(p,[{'claimId':'budget','edits':[{'op':'replace','path':path,'value':'changed'}]}])
    assert result==[] and p==before


def test_pointer_escaping_array_insert_remove_and_per_claim_atomicity():
    p=prepare();p['originals']['budget']['conditions']={'a/b':{'t~x':[1,2]}}
    patch={'claimId':'budget','edits':[{'op':'replace','path':'/conditions/a~1b/t~0x/0','value':3},
        {'op':'add','path':'/conditions/a~1b/t~0x/-','value':4},
        {'op':'remove','path':'/conditions/a~1b/t~0x/1'}]}
    before=deepcopy(p);result=expand(p,[patch]);assert result[0]['conditions']=={'a/b':{'t~x':[3,4]}}
    bad=deepcopy(patch);bad['edits'].append({'op':'replace','path':'/kind','value':'reported'})
    assert expand(p,[bad])==[] and p==before
    assert expand(p,[patch,patch])==[]


def test_foreign_evidence_or_inconsistent_budget_still_fails_existing_checks():
    p=prepare()
    bad_refs=[{'claimId':'budget','edits':[{'op':'replace','path':'/evidenceRefs','value':['foreign']}]}]
    assert _parse_repair_response(p,{'content':json.dumps(bad_refs)},json.loads,strict_response=True)==[]
    bad_budget=[{'claimId':'budget','edits':[{'op':'replace','path':'/executionSpec/recovery/groups/0','value':0}]}]
    revised=_parse_repair_response(p,{'content':json.dumps(bad_budget)},json.loads,strict_response=True)
    check=verify_claims(revised,inputs()[2],lambda *_:[])
    assert not check['accepted'] and any(r['reason']=='incomplete_budget_spec' for r in check['rejected'])


def test_editing_typed_spec_drops_only_old_generated_suffix_and_regenerates_it():
    p=prepare();original=materialize_execution_claim(p['originals']['budget']);p['originals']['budget']=original
    patch=[{'claimId':'budget','edits':[{'op':'replace','path':'/executionSpec/baseline/maxBudget','value':77}]}]
    result=_parse_repair_response(p,{'content':json.dumps(patch)},json.loads,strict_response=True)[0]
    assert verification_claim_view(result)['text']==verification_claim_view(original)['text']
    assert result['executionSpec']['baseline']['maxBudget']==77
    assert result['text'].count('拟议预算')<=1


def test_scheduler_reserves_actual_edit_output_and_freezes_pending_before_dispatch():
    report,checks,evidence=inputs();saved=[];seen=[]
    def invoke(prompt,output):
        assert saved[-1]['pending']['request']['outputTokens']==4096
        assert saved[-1]['pending']['request']['prepared']['editFormatVersion']==1
        seen.append((prompt,output))
        return {'content':json.dumps([{'claimId':c['claimId'],'edits':[
            {'op':'replace','path':'/text','value':'Proposed revised '+c['claimId']}]} for c in report['claims']])}
    args=dict(experimental_intent=3,shared_experiment_schema=True,experimental_edits=True,
        max_prompt_bytes=24000,invoke_request=invoke,checkpoint=lambda s:saved.append(deepcopy(s)))
    revised=repair_rejected(report,checks,evidence,'One scene, two groups with and without a stage.',Mock(),json.loads,**args)
    assert len(seen)==1 and seen[0][1]==OUTPUT_TOKENS==4096 and len(revised)==9
    assert len(saved[-1]['batches'])==1 and 'pending' not in saved[-1]
    again=repair_rejected(report,checks,evidence,'One scene, two groups with and without a stage.',Mock(),json.loads,
        batch_state=saved[-1],**args)
    assert again==revised and len(seen)==1
    with pytest.raises(DeepResearchError,match='原始输入'):
        repair_rejected(report,checks,evidence,'One scene, two groups with and without a stage.',Mock(),json.loads,
            batch_state=saved[-1],experimental_intent=3,shared_experiment_schema=True)


def test_unknown_dispatch_keeps_the_exact_pending_edit_request():
    report,checks,evidence=inputs();saved=[]
    with pytest.raises(OSError):
        repair_rejected(report,checks,evidence,'Question',Mock(),json.loads,
            experimental_intent=3,shared_experiment_schema=True,experimental_edits=True,
            invoke_request=Mock(side_effect=OSError('unknown')),checkpoint=lambda s:saved.append(deepcopy(s)))
    assert saved[-1]['pending']['request']['outputTokens']==4096 and not saved[-1]['results']


def test_missing_typed_objects_and_factual_reports_keep_full_repair_route():
    report,checks,evidence=inputs();assert can_edit(report)
    report['claims'][0].pop('executionSpec');assert not can_edit(report)
    with pytest.raises(ValueError):_prepare_repair(report,checks,evidence,'Question',shared_experiment_schema=True,experimental_edits=True)
    assert not can_edit({'claims':[{'kind':'reported','text':'Actual fact'}]})
