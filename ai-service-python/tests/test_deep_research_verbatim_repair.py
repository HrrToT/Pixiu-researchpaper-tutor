"""Revised prose is a complete candidate, never an editable deletion template."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.repair_removals import preserve_revision, materialize
from services.deep_research.repair import repair_rejected
from test_deep_research_authored_body import prose, boundary, decode, evidence, options


def repair_case(text, spans, *, verbatim=True, saved=None, checkpoint=None):
    original={**decode(prose('c')), 'text':'网格提取路径不同。', 'kind':'inference'}
    raw=prose('c');raw['kind']='inference';raw['evidenceRefs']=['E1']
    raw['body']['prose']['text']=text;raw['discardedDraftSpans']=spans
    invoke=Mock(return_value={'content':json.dumps([raw])})
    opts={**options(),'required_scope_ids':[],'target_goals':5,'verbatim_repair':verbatim}
    result=repair_rejected({'claims':[original]}, {'accepted':[], 'rejected':[{'claimId':'c','reason':'semantic_unresolved'}]},
        evidence(),'比较网格提取路径',invoke,json.loads,batch_state=saved,checkpoint=checkpoint,**opts)
    return result,invoke


def test_observed_negated_retained_phrase_rejects_instead_of_becoming_an_ambiguous_fragment():
    text='证据未说明具体步骤，无法确认两者网格提取路径不同。'
    row={'text':text,'discardedDraftSpans':['网格提取路径不同']}
    old={'text':'网格提取路径不同。'}
    assert materialize(row,old)[0]=='证据未说明具体步骤，无法确认两者。'
    before=deepcopy(row)
    with pytest.raises(ValueError,match='retained'):preserve_revision(row,old)
    assert row==before
    assert repair_case(text,row['discardedDraftSpans'])[0]==[]
    assert repair_case(text,row['discardedDraftSpans'],verbatim=False)[0][0]['text']=='证据未说明具体步骤，无法确认两者。'


@pytest.mark.parametrize('spans',[[],['网格提取路径不同']])
def test_complete_revision_is_preserved_and_checkpoint_cannot_switch_protocol(spans):
    text='当前证据不足以比较两者的网格提取步骤。'
    states=[];result,invoke=repair_case(text,spans,checkpoint=states.append)
    assert result[0]['text']==text and invoke.call_count==1
    assert 'Declarations never edit' in invoke.call_args.args[0]
    saved=deepcopy(states[-1])
    resumed,invoke=repair_case(text,spans,saved=saved)
    assert resumed==result;invoke.assert_not_called()
    from services.deep_research.contracts import DeepResearchError
    with pytest.raises(DeepResearchError):repair_case(text,spans,verbatim=False,saved=saved)
    # A structurally valid revision still has no semantic approval.
    from services.deep_research.verification import verify_claims
    checker=Mock(return_value=[{'claimId':'c','status':'failed','reason':'Fixture unsupported comparison'}])
    assert not verify_claims(result,evidence(),checker)['accepted']
    checker.assert_called_once()


def test_empty_declaration_allows_negation_to_reach_independent_verification_without_editing():
    text='无法确认两者网格提取路径不同。'
    assert repair_case(text,[])[0][0]['text']==text
    _,_,audit=preserve_revision({'text':text,'discardedDraftSpans':[]},{'text':'网格提取路径不同。'})
    assert audit['inputText']==audit['outputText']==text
    assert audit['inputSha256']==audit['outputSha256'] and audit['edits']==[]
    assert audit['verification']=='unchecked'


@pytest.mark.parametrize('value',[True,1.0,None,0,2])
def test_opt_in_requires_exact_server_version(value):
    from services.deep_research.verbatim_repair import enabled
    record={'verbatimRepairContractVersion':value,'factualRepairGoalContractVersion':5,
        'authoredBodyContractVersion':1,'scopeExpressionContractVersion':5,
        'factualPromptContractVersion':3,'state':{'outputKind':'paper_comparison'}}
    assert not enabled(record)
    record['verbatimRepairContractVersion']=1
    assert enabled(record)
    record['factualRepairGoalContractVersion']=5.0
    assert not enabled(record)


@pytest.mark.parametrize('bad',[['不在原句'],['网格','网格'],None,['']])
def test_invalid_declaration_cannot_be_silently_ignored(bad):
    with pytest.raises(ValueError):preserve_revision({'text':'完整新句。','discardedDraftSpans':bad},{'text':'网格。'})


@pytest.mark.parametrize('retained',[False,True])
def test_boundary_is_checked_after_rendering_and_never_trimmed(retained):
    original={**decode(prose('c')),'kind':'inference','text':'作者从未报告显存。','evidenceRefs':['a','b']}
    raw=boundary();raw['evidenceRefs']=['E1','E2'];raw['discardedDraftSpans']=['作者从未报告显存']
    if retained:raw['body']['boundary']['notEstablished'][0]['quantity']='作者从未报告显存'
    result=repair_rejected({'claims':[original]},{'accepted':[],'rejected':[{'claimId':'c','reason':'semantic_unresolved'}]},
        evidence(),'比较A和B的显存',Mock(return_value={'content':json.dumps([raw])}),json.loads,
        target_goals=5,verbatim_repair=True,**options())
    assert bool(result) is (not retained)
    if result:assert result[0]['text']=='当前引用不足以比较A与B的显存。'


@pytest.mark.parametrize('value',[True,False,0,2,None])
def test_server_owned_flag_is_immutable_and_legacy_records_remain_unchanged(tmp_path,value):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'比较论文','deferStart':True,
            'verbatimRepairContractVersion':value},start_async=False)
        assert type(r['verbatimRepairContractVersion']) is int and r['verbatimRepairContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(r['runId'],lambda r:{**r,'verbatimRepairContractVersion':value})
        old=deepcopy(r);old.update(runId='legacy',idempotencyKey='old');old.pop('verbatimRepairContractVersion')
        repo.create_run(old);before=repo.require_run('legacy')
        facade.create({'workspaceTaskId':'t','operationKey':'next','question':'比较论文','deferStart':True},start_async=False)
        assert repo.require_run('legacy')==before
    finally:facade.shutdown()
