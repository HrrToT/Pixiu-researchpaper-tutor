"""Coverage reasons identify unmet targets without changing support or retries."""
from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.final_coverage import audit_final_answer
from services.deep_research.coverage_diagnostics import validate, enabled, GUIDANCE
from services.deep_research.coverage_repair import prepare_coverage_repair
from test_deep_research_final_coverage import PLAN, CLAIMS, verdicts

QUESTION='标定所需条件是什么？'
EVIDENCE=[{'evidenceId':'e','quote':'Calibration requires known camera intrinsics and a fixed evaluation split.',
           'sourceWorkId':'paper','sourceVersionId':'v','sourceContext':
           'Original context. Calibration requires known camera intrinsics and a fixed evaluation split. Following context.'}]


def rows():
    value=verdicts('partial')
    for row in value:
        row['gapDetail']={'criterionIds':[],'aspectIds':['conditions'],
            'missingContent':'说明标定所需的几何前提。',
            'reason':'当前回答只列出了内参和评测划分，没有交代几何前提。'}
    return value


def audit(value,diagnostics=True):
    invoke=Mock(return_value={'content':json.dumps(value)})
    result=audit_final_answer('r',QUESTION,PLAN,CLAIMS,EVIDENCE,invoke,json.loads,diagnostics=diagnostics)
    assert invoke.call_count==1
    return result,invoke


def test_actionable_partial_is_bound_to_actual_targets_and_reaches_only_private_repair_input():
    value=rows();before=deepcopy(value);result,invoke=audit(value)
    assert result['status']=='checked' and result['diagnosticErrors']==[]
    assert result['gaps'][0]['gapDetail']==value[0]['gapDetail']
    assert result['gaps'][0]['missingAspects']==['必要条件']
    assert GUIDANCE in invoke.call_args.args[2] and value==before
    repaired=prepare_coverage_repair({'claims':CLAIMS},{'accepted':CLAIMS,'rejected':[]},result)
    hints=repaired['rejected'][0]['missingQuestions']
    assert any(value[0]['gapDetail']['missingContent'] in s for s in hints)
    assert any('未核实的完整性诊断' in s for s in hints)
    assert CLAIMS[0]['text']=='相机标定需要已知内参，并固定评测图像划分。'
    assert repaired['accepted']==[]  # A reason does not approve the answer.


@pytest.mark.parametrize('mutation',[
    'missing','empty_reason','empty_content','overlong','unknown_aspect','omit_target',
    'duplicate_target','foreign_criterion','extra_field','contradictory_covered','duplicate_obligation'])
def test_missing_unbound_and_contradictory_reasons_are_invalid_not_coverage_or_factual_passes(mutation):
    value=rows();detail=value[0]['gapDetail']
    if mutation=='missing':value[0].pop('gapDetail')
    elif mutation=='empty_reason':detail['reason']=' '
    elif mutation=='empty_content':detail['missingContent']=''
    elif mutation=='overlong':detail['reason']=' '*900+'x'
    elif mutation=='unknown_aspect':detail['aspectIds']=['other']
    elif mutation=='omit_target':detail['aspectIds']=[]
    elif mutation=='duplicate_target':detail['aspectIds']*=2
    elif mutation=='foreign_criterion':detail['criterionIds']=['other']
    elif mutation=='extra_field':detail['status']='covered'
    elif mutation=='contradictory_covered':value[0]['status']='covered';value[0]['aspects'][0]['status']='covered'
    else:value.append(deepcopy(value[0]))
    result,_=audit(value)
    assert result['status']=='invalid_response' and result['diagnosticErrors']
    assert result['gaps']
    assert all(g['auditStatus']=='invalid_response' for g in result['gaps'])


def test_existing_partial_without_reason_remains_legacy_partial_and_is_not_upgraded():
    value=verdicts('partial')
    legacy,invoke=audit(value,False)
    new,_=audit(value,True)
    assert legacy['status']=='checked' and 'diagnosticErrors' not in legacy
    assert GUIDANCE not in invoke.call_args.args[2]
    assert new['status']=='invalid_response' and all(v['status']=='partial' for v in new['verdicts'])


def test_covered_with_missing_child_is_still_rejected_without_a_bound_diagnostic():
    value=verdicts();value[0]['aspects'][0].update(status='missing',bindings=[])
    result,_=audit(value)
    assert result['status']=='invalid_response' and result['verdicts'][0]['status']=='partial'
    assert result['diagnosticErrors']==['o']


def test_covered_answer_does_not_need_or_receive_an_invented_gap():
    value=verdicts()
    for row in value:
        row['aspects'][0]['basis']={'kind':'source','evidenceId':'E1','field':'quote'}
    result,_=audit(value)
    assert result['status']=='checked' and result['gaps']==[] and result['diagnosticErrors']==[]


def test_diagnostic_targets_require_every_unmet_criterion_and_aspect():
    value=rows();v=value[0]
    v['criteria']=[{'criterionId':'k','status':'partial'}]
    assert validate(value,['o','answer_scope'])[0]==['o']
    v['gapDetail']['criterionIds']=['k']
    assert validate(value,['o','answer_scope'])[0]==[]
    v['aspects'][0]['status']='covered';v['gapDetail']['aspectIds']=[]
    assert validate(value,['o','answer_scope'])[0]==[]


def test_unknown_outcome_propagates_and_does_not_resend():
    from services.deep_research.contracts import DeepResearchError
    invoke=Mock(side_effect=DeepResearchError('call_unknown','unknown'))
    with pytest.raises(DeepResearchError):
        audit_final_answer('r',QUESTION,PLAN,CLAIMS,EVIDENCE,invoke,json.loads,diagnostics=True)
    assert invoke.call_count==1


def test_missing_required_source_is_an_invalid_audit_before_send():
    invoke=Mock()
    result=audit_final_answer('r',QUESTION,PLAN,CLAIMS,[],invoke,json.loads,diagnostics=True)
    assert result['status']=='invalid_response' and result['diagnosticErrors']
    invoke.assert_not_called()


def test_cited_context_is_preserved_before_optional_evidence_and_never_truncated():
    from services.deep_research.coverage_diagnostics import fit_complete_context
    from services.deep_research.contracts import BudgetExhaustedError
    own={'evidenceId':'own','quote':'Original quotation.','sourceContext':{'before':'Context. '*30}}
    optional={'evidenceId':'extra','quote':'Optional. '*50,'sourceContext':{'before':'Other.'}}
    source=[optional,own];before=deepcopy(source)
    render=lambda rows:'Instructions\n'+json.dumps(rows)
    limit=len(render([own]).encode())
    prompt,selected=fit_complete_context(source,render,limit,{'own'})
    assert selected==[own] and prompt==render([own]) and source==before
    with pytest.raises(BudgetExhaustedError):fit_complete_context(source,render,limit-1,{'own'})
    with pytest.raises(ValueError):fit_complete_context(source,render,limit,{'missing'})


def test_large_cited_quote_is_not_silently_dropped_to_obtain_a_diagnostic():
    evidence=deepcopy(EVIDENCE);evidence[0]['quote']='original '*4000
    evidence[0]['sourceContext']='Before. '+evidence[0]['quote']+' After.'
    invoke=Mock()
    result=audit_final_answer('r',QUESTION,PLAN,CLAIMS,evidence,invoke,json.loads,diagnostics=True)
    assert result['status']=='budget_exhausted' and result['gaps']
    invoke.assert_not_called()


@pytest.mark.parametrize('marker',[None,1,2])
def test_real_verify_node_passes_only_the_server_policy_to_coverage(monkeypatch,marker):
    from services.deep_research.graph import make_verify_node
    record={'question':QUESTION,'state':{'plan':PLAN,'reportBody':{'claims':CLAIMS},
        'evidence':[],'outputKind':'claim_verification','gaps':[]}}
    if marker is not None:record['coverageDiagnosticsContractVersion']=marker
    def update(_id,fn,**kw):
        nonlocal record
        record=fn(deepcopy(record));return deepcopy(record)
    capture=Mock(return_value={'status':'checked','gaps':[]})
    monkeypatch.setattr('services.deep_research.final_coverage.audit_final_answer',capture)
    make_verify_node(lambda *a:{'accepted':CLAIMS,'rejected':[]},None,update,Mock())({'run_id':'r'})
    assert capture.call_args.kwargs.get('binding_catalog')==(True if marker==2 else None)
    assert capture.call_count==1
    assert capture.call_args.kwargs.get('diagnostics')==(True if marker in (1,2) else None)


@pytest.mark.parametrize('replacement',[None,0,True,'1',3])
def test_policy_is_server_owned_immutable_and_never_migrates_old_runs(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'first','question':QUESTION,
            'deferStart':True,'coverageDiagnosticsContractVersion':replacement},start_async=False)
        assert enabled(run)
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(run['runId'],lambda r:{**r,'coverageDiagnosticsContractVersion':replacement})
        old=deepcopy(run);old.update(runId='old',idempotencyKey='old');old.pop('coverageDiagnosticsContractVersion')
        repo.create_run(old);before=repo.require_run('old')
        assert not enabled(before)
        facade.create({'workspaceTaskId':'t','operationKey':'next','question':QUESTION,'deferStart':True},start_async=False)
        assert repo.require_run('old')==before
    finally:facade.shutdown()
