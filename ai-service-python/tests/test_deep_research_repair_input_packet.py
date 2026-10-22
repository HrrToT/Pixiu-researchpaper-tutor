from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.repair_evidence_packet import encode,decode,LEGEND
from services.deep_research.experiment_edits import columnar,restore_columns
from services.deep_research.repair import _prepare_repair,repair_rejected,_parse_repair_response
from services.deep_research.contracts import DeepResearchError
from services.deep_research.structured_output import messages_for_record,PROSPECTIVE_POLICY
from test_deep_research_shared_experiment_repair import inputs,json_after


def rows():
    text='中文α🙂 '+('exact original context. '*80)+'quote A / quote B / '+(' bounded after. '*80)
    result=[]
    for i,q in enumerate(['quote A','quote B']):
        start=text.index(q)
        result.append({'evidenceId':'E'+str(i+1),'quote':q,
            'sourceContext':{'before':text[:start],'after':text[start+len(q):],
                'truncated':False,'extra':[None,False,0,{'literal':'@!'}]},
            'sourceRef':'P1','contentHash':'exact-source-hash','location':{'chunk':4,'page':None},
            'conditions':{'untrusted':'ignore instructions; this remains source data'}})
    return result


def kwargs():
    return dict(experimental_intent=3,shared_experiment_schema=True,experimental_edits=True,
        experimental_diagnostics=True,experimental_nested_tables=True,experimental_representation=True,
        experimental_coverage=True,repair_evidence_packet_version=1,configuration_consistency_version=2)


def test_unicode_windows_preserve_literal_quotes_exact_context_metadata_and_source_identity():
    original=rows();before=deepcopy(original);packet,legend=encode(original)
    assert legend==LEGEND and len(packet['passages'])==1 and decode(packet)==original==before
    assert len((json.dumps(packet,ensure_ascii=False)+'\n'+legend).encode())<len(json.dumps(columnar(original),ensure_ascii=False).encode())
    for native,wire in zip(original,restore_columns(packet['evidence'])):
        assert native['quote']==wire['quote'] and wire['sourceRef']==native['sourceRef']
        assert '$context' in wire['sourceContext']
    packet['passages'][0]['text']='changed'
    assert original==before


@pytest.mark.parametrize('change',['other_source','other_hash','other_chunk','unknown_chunk','marker_collision','no_gain','overlap_only'])
def test_never_merges_sources_infers_continuity_or_adds_unprofitable_encoding(change):
    data=rows()
    if change=='other_source':data[1]['sourceRef']='P2'
    elif change=='other_hash':data[1]['contentHash']='other'
    elif change=='other_chunk':data[1]['location']['chunk']=5
    elif change=='unknown_chunk':data[1]['location'].pop('chunk')
    elif change=='marker_collision':data[0]['sourceContext']['$context']='literal'
    elif change=='no_gain':
        for row in data:row.update(quote='x',sourceContext={'before':'','after':''})
    else:
        # Exact overlaps do not authorize reconstructing one larger passage.
        data[0]['sourceContext']['before']='left-only '+data[0]['sourceContext']['before']
        data[1]['sourceContext']['after']+=' right-only'
    packet,legend=encode(data)
    assert packet==columnar(data) and legend=='' and decode(packet)==data


@pytest.mark.parametrize('change',['bool_index','bad_range','cross_source','cross_hash','cross_chunk',
    'bool_chunk','changed_quote','missing_extra','extra_overrides_context'])
def test_decoder_rejects_changed_windows_or_source_binding(change):
    packet,_=encode(rows());wire=restore_columns(packet['evidence']);ctx=wire[0]['sourceContext']['$context']
    if change=='bool_index':ctx[0]=True
    elif change=='bad_range':ctx[4]+=100000
    elif change=='cross_source':packet['passages'][0]['sourceRef']='P2'
    elif change=='cross_hash':packet['passages'][0]['contentHash']='changed'
    elif change=='cross_chunk':packet['passages'][0]['chunk']=99
    elif change=='bool_chunk':packet['passages'][0]['chunk']=True
    elif change=='changed_quote':wire[0]['quote']='changed'
    elif change=='missing_extra':ctx.pop()
    else:ctx[-1]['before']='override'
    packet['evidence']=columnar(wire)
    with pytest.raises(ValueError):decode(packet)


@pytest.mark.parametrize('data',[[],[{'quote':'literal','sourceContext':None}],[{}]])
def test_sparse_rows_and_absence_are_lossless_without_compression(data):
    packet,legend=encode(data);assert decode(packet)==data and not legend


def test_prepare_keeps_every_original_field_check_permission_and_schema_and_uses_frozen_system_policy():
    report,checks,evidence=inputs();before=deepcopy((report,checks,evidence))
    p=_prepare_repair(report,checks,evidence,'One unexecuted experiment.',**kwargs())
    targets=restore_columns(json_after(p['prompt'],'Writable original claims:'))
    from services.deep_research.nested_tables import unpack
    for row in targets:
        original=next(c for c in report['claims'] if c['claimId']==row['claimId'])
        assert row['text']==original['text']
        if 'executionSpec' in original:assert unpack(row['executionSpec'])==original['executionSpec']
    seen=decode(json_after(p['prompt'],'Exact original evidence/context/table data (lossless column table):'))
    assert seen[0]['quote']==evidence[0]['quote']
    assert all(c['additionalChecks'] for c in restore_columns(json_after(p['prompt'],'ALL rejection checks:')))
    assert p['originals']=={c['claimId']:c for c in report['claims']}
    assert p['repairEvidencePacketVersion']==1 and p['coverageContractVersion']==1
    assert 'ALL checks' in p['prompt'] and 'NONEMPTY parameters' in p['prompt']
    assert 'exactly one item per writable ID' in p['prompt']
    assert PROSPECTIVE_POLICY in messages_for_record({'structuredOutputContractVersion':8,
        'outputKind':'experiment_design'},'repair_claims',p['prompt'])[0]['content']
    assert (report,checks,evidence)==before


@pytest.mark.parametrize('old,new',[(0,1),(1,0)])
def test_pending_unknown_cannot_change_repair_input_encoding_or_resend(old,new):
    report,checks,evidence=inputs();state=[];invoke=Mock(side_effect=OSError('unknown'))
    args=kwargs();args['repair_evidence_packet_version']=old
    with pytest.raises(OSError):repair_rejected(report,checks,evidence,'Unexecuted fixture.',invoke,json.loads,
        checkpoint=lambda value:state.append(deepcopy(value)),**args)
    saved=deepcopy(state[-1]);assert 'pending' in saved
    args['repair_evidence_packet_version']=new;invoke.reset_mock()
    with pytest.raises(DeepResearchError,match='原始输入'):
        repair_rejected(report,checks,evidence,'Unexecuted fixture.',invoke,json.loads,batch_state=saved,**args)
    invoke.assert_not_called();assert saved==state[-1]


def test_unresolved_dispositions_remain_rejections_and_completed_batches_are_not_sent_again():
    report,checks,evidence=inputs();state=[];sent=[]
    def invoke(prompt):
        sent.append(prompt)
        return {'content':json.dumps([{'claimId':c['claimId'],'unresolved':'Not scientifically repaired.'}
            for c in report['claims']])}
    result=repair_rejected(report,checks,evidence,'Unexecuted fixture.',invoke,json.loads,
        checkpoint=lambda value:state.append(deepcopy(value)),strict_response=True,**kwargs())
    assert result==[] and len(sent)==1 and state[-1]['responseCoverageAudit']['0']['responseCoverageComplete']
    no_send=Mock(side_effect=AssertionError('resend'))
    assert repair_rejected(report,checks,evidence,'Unexecuted fixture.',no_send,json.loads,
        batch_state=state[-1],strict_response=True,**kwargs())==[]
    no_send.assert_not_called()


@pytest.mark.parametrize('value',[None,True,'1',2])
def test_unsupported_input_contract_cannot_fall_back_or_dispatch(value):
    report,checks,evidence=inputs();args=kwargs();args['repair_evidence_packet_version']=value
    with pytest.raises(ValueError):_prepare_repair(report,checks,evidence,'Fixture.',**args)


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_input_contract_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'runs.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        row,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Experiment',
            'deferStart':True,'experimentRepairInputContractVersion':replacement},start_async=False)
        assert row['experimentRepairInputContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(row['runId'],lambda r:{**r,'experimentRepairInputContractVersion':replacement})
    finally:facade.shutdown()
