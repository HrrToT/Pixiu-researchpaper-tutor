from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.repair_coverage import add_contract,partition
from services.deep_research.repair import _prepare_repair,_parse_repair_response,repair_rejected
from services.deep_research.contracts import DeepResearchError
from test_deep_research_shared_experiment_repair import inputs

OPTIONS=dict(experimental_intent=3,shared_experiment_schema=True,experimental_edits=True,
    experimental_diagnostics=True,experimental_nested_tables=True,experimental_representation=True)


def edit(cid,path='/text',value='Revised unexecuted choice.'):
    return {'claimId':cid,'edits':[{'op':'replace','path':path,'value':value}]}


def test_complete_dispositions_preserve_originals_and_do_not_approve_unresolved_targets():
    originals={'a':{},'b':{}};response=[edit('a'),{'claimId':'b','unresolved':'The source does not resolve this initialization.'}]
    before=deepcopy((originals,response));edits,audit=partition(originals,response)
    assert edits==[response[0]] and audit['responseCoverageComplete']
    assert audit['unresolvedTargets']==[{'claimId':'b','reason':response[1]['unresolved']}]
    assert audit['scientificApproval'] is False and not audit['missingTargetIds']
    assert (originals,response)==before


@pytest.mark.parametrize('response',[
    [],[edit('a')],[edit('a'),edit('a')],[edit('other')],
    [{'claimId':'a','edits':[]}],[{'claimId':'a','unresolved':''}],
    [{'claimId':'a','unresolved':'x'*601}],[{'claimId':'a','unresolved':'specific','extra':True}],
    [None],[{'claimId':True,'edits':[{}]}],
    [{'claimId':'a','edits':[{}],'unresolved':'conflicting disposition'}]])
def test_missing_duplicate_invalid_and_foreign_dispositions_never_count_as_complete(response):
    edits,audit=partition({'a':{},'b':{}},response)
    assert audit['missingTargetIds'] and not audit['responseCoverageComplete']
    assert not audit['scientificApproval']
    assert all(r['claimId'] in {'a','b'} for r in edits)


def test_new_prompt_covers_every_writable_target_while_schema_feedback_remains_only_hints():
    report,checks,evidence=inputs()
    old=_prepare_repair(report,checks,evidence,'Q',**OPTIONS)
    new=_prepare_repair(report,checks,evidence,'Q',**OPTIONS,experimental_coverage=True)
    assert new['coverageContractVersion']==1 and 'coverageContractVersion' not in old
    assert set(new['originals'])==set(old['originals'])
    assert new['allowed']==old['allowed'] and new['aliases']==old['aliases']
    assert 'Schema-feedback targets are additional syntax hints' in new['prompt']
    ids=list(new['originals']);assert json.dumps(ids,separators=(',',':')) in new['prompt']
    assert 'replace|add|remove' in new['prompt'] and '/tableBindings' in new['prompt']
    assert 'required except remove' in new['prompt']
    assert len(new['prompt'].encode())<=24000 and new['prompt']!=old['prompt']
    assert 'unresolved' not in old['prompt'].split('Return ONLY [',1)[1].split('\n',1)[0]


def test_partial_response_records_exact_missing_set_without_manufacturing_revisions():
    report,checks,evidence=inputs();prepared=_prepare_repair(report,checks,evidence,'Q',**OPTIONS,experimental_coverage=True)
    ids=list(prepared['originals']);audit=[]
    result=_parse_repair_response(prepared,{'content':json.dumps([edit(ids[0]),edit(ids[1])])},json.loads,coverage_audit=audit)
    assert [r['claimId'] for r in result]==ids[:2]
    assert audit[0]['missingTargetIds']==ids[2:] and audit[0]['expandedRevisionIds']==ids[:2]
    assert not audit[0]['responseCoverageComplete'] and all('verification' not in r for r in result)


@pytest.mark.parametrize('path,value',[('/evidenceRefs',['FOREIGN']),('/claimId','foreign'),('/kind','reported'),('/executionSpec/no_such_parent/x',1)])
def test_coverage_does_not_bypass_original_permissions_or_edit_shape(path,value):
    report,checks,evidence=inputs();prepared=_prepare_repair(report,checks,evidence,'Q',**OPTIONS,experimental_coverage=True)
    ids=list(prepared['originals']);raw=[edit(ids[0],path,value),*[{'claimId':cid,'unresolved':'Needs a supported specification.'} for cid in ids[1:]]]
    audit=[];result=_parse_repair_response(prepared,{'content':json.dumps(raw)},json.loads,coverage_audit=audit)
    assert not result and audit[0]['unusableEditTargetIds']==[ids[0]]
    assert audit[0]['scientificApproval'] is False


def test_truncation_is_known_incomplete_response_not_an_unknown_or_success():
    report,checks,evidence=inputs();prepared=_prepare_repair(report,checks,evidence,'Q',**OPTIONS,experimental_coverage=True)
    audit=[];assert not _parse_repair_response(prepared,{'finishReason':'length','content':'['},json.loads,coverage_audit=audit)
    assert audit[0]['responseState']=='received_truncated'
    assert audit[0]['missingTargetIds']==list(prepared['originals'])


def test_partial_batch_is_checkpointed_once_and_resume_never_resends_it():
    report,checks,evidence=inputs();cid=report['claims'][0]['claimId'];saved=[]
    invoke=Mock(return_value={'content':json.dumps([edit(cid)])})
    args={**OPTIONS,'experimental_coverage':True,'invoke_request':invoke}
    result=repair_rejected(report,checks,evidence,'Q',Mock(),json.loads,**args,checkpoint=lambda s:saved.append(deepcopy(s)))
    assert invoke.call_count==1 and [r['claimId'] for r in result]==[cid]
    coverage=saved[-1]['responseCoverageAudit']['0'];assert len(coverage['missingTargetIds'])==len(report['claims'])-1
    assert 'pending' not in saved[-1]
    invoke.reset_mock()
    assert repair_rejected(report,checks,evidence,'Q',Mock(),json.loads,**args,batch_state=saved[-1])==result
    invoke.assert_not_called()


def test_unknown_pending_identity_is_not_upgraded_to_new_response_semantics():
    report,checks,evidence=inputs();saved=[];invoke=Mock(side_effect=OSError('unknown'))
    with pytest.raises(OSError):
        repair_rejected(report,checks,evidence,'Q',Mock(),json.loads,**OPTIONS,invoke_request=invoke,
            checkpoint=lambda s:saved.append(deepcopy(s)))
    frozen=deepcopy(saved[-1]);invoke.reset_mock()
    with pytest.raises(DeepResearchError,match='原始输入'):
        repair_rejected(report,checks,evidence,'Q',Mock(),json.loads,**OPTIONS,experimental_coverage=True,
            invoke_request=invoke,batch_state=frozen)
    invoke.assert_not_called();assert saved[-1]==frozen


def test_unrelated_prompt_cannot_opt_into_an_unfrozen_response_contract():
    with pytest.raises(ValueError):add_contract('No experimental response grammar here',{'a':{}})
    report,checks,evidence=inputs()
    with pytest.raises(ValueError):_prepare_repair(report,checks,evidence,'Q',experimental_coverage=True)
