"""A fixed scope does not require repeating its boundary in editable prose."""
from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.compaction_editing import GUIDANCE
from services.deep_research.contracts import DeepResearchError
from services.deep_research.repair_compaction import compact_repairs
from services.deep_research.scope_compaction import compact
from test_deep_research_compaction_editing import inputs
from test_deep_research_preferred_scope_edit import options,edit


def test_fixed_editor_receives_selective_permissions_without_changing_scope_or_metadata():
    report,audits,_=inputs();before=deepcopy((report,audits));direct=Mock(return_value={'content':json.dumps(edit())});joint=Mock()
    out,new=compact(report,audits,'100字以内',joint,json.loads,invoke_fixed=direct,selective_fixed_edit=True,**options())
    assert out and out['claims'][1]==report['claims'][1] and (report,audits)==before
    assert new[0]['expression']==audits[0]['expression'] and new[0]['verification']=='unchecked'
    prompt=direct.call_args.args[0]
    assert GUIDANCE in prompt and '只精简措辞，不新增或强化事实' not in prompt
    assert '与只读内容重复的说明' in prompt and '独有的必答内容' in prompt
    for old,row in zip(report['claims'],out['claims']):
        assert all(row[k]==old[k] for k in ('kind','evidenceRefs','obligationIds','detailLevel','tableBindings'))
    direct.assert_called_once();joint.assert_not_called()


def test_legacy_preferred_prompt_and_checkpoint_are_exact_until_new_policy_selected():
    report,audits,_=inputs();direct=Mock(return_value={'content':json.dumps(edit())});joint=Mock();states=[]
    args=(report,report['claims'],[],{'scopeExpressionAudit':{'0':audits}},'100字以内',joint,json.loads)
    old=compact_repairs(*args,invoke_fixed=direct,checkpoint=states.append,**options());old_prompt=direct.call_args.args[0];old_state=deepcopy(states[-1])
    same=compact_repairs(*args,invoke_fixed=direct,checkpoint=states.append,selective_fixed_edit=False,**options())
    assert same==old and direct.call_args.args[0]==old_prompt and states[-1]==old_state and GUIDANCE not in old_prompt
    direct.reset_mock()
    with pytest.raises(DeepResearchError,match='输入不一致'):
        compact_repairs(*args,invoke_fixed=direct,saved=old_state,selective_fixed_edit=True,**options())
    direct.assert_not_called()
    new=[];out=compact_repairs(*args,invoke_fixed=direct,checkpoint=new.append,selective_fixed_edit=True,**options())
    assert out and new[-1]['inputDigest']!=old_state['inputDigest'];direct.reset_mock()
    assert compact_repairs(*args,invoke_fixed=direct,saved=new[-1],selective_fixed_edit=True,**options())==out
    direct.assert_not_called();joint.assert_not_called()


@pytest.mark.parametrize('mutation',['oversize','foreign','readonly','blank','extra','truncated'])
def test_edit_permissions_do_not_weaken_shape_length_or_readonly_guards(mutation):
    report,audits,_=inputs();response=edit();row=response['claims'][0]
    if mutation=='oversize':row['text']='长'*200
    elif mutation=='foreign':row['claimId']='unknown'
    elif mutation=='readonly':row['claimId']='c'
    elif mutation=='blank':row['text']=' '
    elif mutation=='extra':row['evidenceRefs']=['foreign']
    direct=Mock(return_value={'content':json.dumps(response),'finishReason':'length' if mutation=='truncated' else 'stop'});joint=Mock()
    out,new=compact(report,audits,'100字以内',joint,json.loads,invoke_fixed=direct,selective_fixed_edit=True,**options())
    assert out is None and new==audits;direct.assert_called_once();joint.assert_not_called()


@pytest.mark.parametrize('value',[None,0,1,'1'])
def test_invalid_flag_rejected_before_any_dispatch(value):
    report,audits,_=inputs();invoke=Mock()
    with pytest.raises(ValueError):compact(report,audits,'100字以内',invoke,json.loads,selective_fixed_edit=value,**options())
    with pytest.raises(ValueError):compact_repairs(report,report['claims'],[],{},'100字以内',invoke,json.loads,selective_fixed_edit=value,**options())
    invoke.assert_not_called()


@pytest.mark.parametrize('missing',['selective_editing','prefer_fixed_scope','explicit_edit_scope'])
def test_requires_explicit_selective_preferred_scope(missing):
    report,audits,_=inputs();invoke=Mock();kwargs=options();kwargs.pop(missing)
    with pytest.raises(ValueError):compact(report,audits,'100字以内',invoke,json.loads,selective_fixed_edit=True,**kwargs)
    invoke.assert_not_called()
