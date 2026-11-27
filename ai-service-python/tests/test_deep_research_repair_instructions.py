from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.repair import _prepare_repair,repair_rejected
from services.deep_research.repair_instructions import enabled
from test_deep_research_authored_body import prose,decode,evidence,options


def fixture():
    original=decode(prose('c'))
    report={'claims':[original]}
    verification={'accepted':[],'rejected':[{'claimId':'c','reason':'answer_incomplete','missingQuestions':['Explain the operation.']}]}
    opts={**options(),'required_scope_ids':[],'target_goals':5,'verbatim_repair':True}
    return report,verification,evidence(),opts


def comparison_fixture():
    report, verification, ev, opts = fixture()
    report['comparisonCells'] = {'version': 3, 'sources': {}, 'layout': []}
    opts.update(consolidated_instructions=True, compact_repair_policy=2, comparison_authoring=True)
    return report, verification, ev, opts


def test_process_repair_preserves_supported_signal_boundaries_without_new_permissions():
    report, verification, ev, opts = fixture()
    old = _prepare_repair(report, verification, ev, 'Explain the operation.', **opts, process_explanations=True)
    new = _prepare_repair(report, verification, ev, 'Explain the operation.', **opts, process_explanations=2)
    assert new['originals'] == old['originals'] and new['allowed'] == old['allowed']
    assert 'which steps can carry a signal' not in old['prompt']
    assert 'which steps can carry a signal' in new['prompt']
    assert 'beyond the destination the user asked about' in new['prompt']


def test_reader_repair_keeps_a_plain_operation_and_learning_target_in_the_existing_call():
    report, verification, ev, opts = fixture()
    question = '向初学者解释如何用这个损失训练，限200字。'
    old = _prepare_repair(report, verification, ev, question, **opts, process_explanations=2)
    new = _prepare_repair(report, verification, ev, question, **opts, process_explanations=3)
    for field in ('originals','allowed','aliases'):
        assert new[field] == old[field]
    assert 'which prediction it rewards or penalizes' in new['prompt']
    assert 'which prediction it rewards or penalizes' not in old['prompt']
    assert 'beyond the destination the user asked about' in new['prompt']


def test_comparison_repair_omits_deletion_declarations_but_keeps_originals_and_evidence():
    report, verification, ev, opts = comparison_fixture()
    old_opts = {**opts, 'comparison_authoring': False}
    old = _prepare_repair(report, verification, ev, 'Explain the operation.', **old_opts)
    new = _prepare_repair(report, verification, ev, 'Explain the operation.', **opts)
    assert new['originals'] == old['originals'] and new['allowed'] == old['allowed']
    assert new['aliases'] == old['aliases']
    assert 'repairRemovalContractVersion' not in new
    assert new['comparisonAuthoringContractVersion'] == 1
    assert 'discardedDraftSpans' not in new['prompt']
    assert 'unverifiedPointHints' not in new['prompt']
    assert all(e['quote'] in new['prompt'] for e in ev if e['evidenceId'] in new['allowed']['c'])
    assert len(new['prompt'].encode()) < len(old['prompt'].encode())


def test_comparison_repair_carries_the_frozen_benchmark_owner_and_preserves_sources():
    report, verification, ev, opts = comparison_fixture()
    opts['comparison_authoring'] = 4
    question = 'Explain the operation.'
    old = _prepare_repair(report, verification, ev, question, **opts)
    new = _prepare_repair(report, verification, ev, question, **opts, benchmark_example={'claimId': 'joint_example'})
    assert 'benchmarkExample.claimId' not in old['prompt']
    assert 'Only benchmarkExample.claimId may include numerical benchmark results' in new['prompt']
    assert 'do not claim that the paper did not report it' in new['prompt']
    assert 'joint_example' in new['prompt']
    for field in ('allowed', 'originals', 'aliases', 'comparisonDisplayEvidence'):
        assert new[field] == old[field]


def test_repair_resolves_visible_cells_and_leaves_prose_without_coordinates():
    from services.deep_research.repair import _parse_repair_response
    report, verification, ev, opts = comparison_fixture()
    ev[0].update(quote='Table row 8: Ours-30K | 134',
                 tableData={'groups': [['Benchmark', ['FPS']]],
                            'rows': [[8, 'Ours-30K', ['134']]]})
    prepared = _prepare_repair(report, verification, ev, 'Explain the operation.',
                               **{**opts, 'comparison_authoring': 2})
    ref, = prepared['comparisonCellRegistry']
    evidence_id = prepared['comparisonCellRegistry'][ref]['binding']['evidenceId']
    assert ref in prepared['prompt'] and 'tableCatalog' in prepared['prompt']
    assert prepared['comparisonAuthoringContractVersion'] == 2
    plain_input = {key: value for key, value in prose('c').items()
                   if key not in {'obligationIds', 'tableBindings'}}
    measured = {**deepcopy(plain_input), 'evidenceRefs': [evidence_id], 'cellRefs': [ref]}
    measured['body']['prose']['text'] = 'Benchmark 上 Ours-30K 为 134 FPS。'

    def parse(row):
        return _parse_repair_response(prepared, {'content': json.dumps([row])}, json.loads)

    compiled, = parse(measured)
    assert compiled['tableBindings'] == [{'evidenceId': ev[0]['evidenceId'], 'rowNumber': 8,
                                          'groupIndex': 0, 'metric': 'FPS', 'value': '134'}]
    assert compiled['conditions']['原表测量'] == 'Benchmark / Ours-30K：FPS 134'
    assert not parse({**measured, 'cellRefs': ['Vinvented']})
    assert not parse({**measured, 'cellRefs': [ref, ref]})
    assert not parse({**measured, 'tableBindings': compiled['tableBindings']})
    assert not parse({**measured, 'evidenceRefs': ['E99']})
    plain, = parse({**plain_input, 'evidenceRefs': [evidence_id], 'cellRefs': []})
    assert plain['tableBindings'] == [] and '原表测量' not in plain['conditions']


def test_comparison_repair_example_matches_native_envelope_and_named_conditions():
    from services.deep_research.contracts import DeepResearchError
    from services.deep_research.graph import _safe_parse_json
    from services.deep_research.repair import _parse_repair_response
    from services.deep_research.structured_output import normalize

    report, verification, ev, opts = comparison_fixture()
    old = _prepare_repair(report, verification, ev, 'Explain the operation.',
                          **{**opts, 'comparison_authoring': 3})
    new = _prepare_repair(report, verification, ev, 'Explain the operation.',
                          **{**opts, 'comparison_authoring': 4})
    assert new['originals'] == old['originals'] and new['allowed'] == old['allowed']
    assert new['aliases'] == old['aliases']
    assert 'Return a JSON array' not in new['prompt']
    example = next(line for line in new['prompt'].splitlines() if line.startswith('{"items":[{'))
    row, = json.loads(example)['items']
    row['claimId'] = 'c'
    row['kind'] = report['claims'][0]['kind']
    row['evidenceRefs'] = [next(k for k, v in new['aliases'].items() if v in new['allowed']['c'])]

    def parse(content):
        response = normalize('repair_claims', {'content': content, 'finishReason': 'stop'})
        return _parse_repair_response(new, response, _safe_parse_json, strict_response=True)

    raw = json.dumps({'items': [row]})
    compiled, = parse(raw)
    assert compiled['conditions'] == {'dataset': 'Observed dataset'}
    with pytest.raises(DeepResearchError, match='未能解析'):
        parse(raw.replace('"dataset": ', ''))


def test_comparison_compact_repair_keeps_distinct_versions_requirements_and_diagnostics():
    from services.deep_research.comparison_repair import compact_inputs
    question = 'Compare the methods under their actual test conditions.'
    criterion = 'Give the tested resolution.'
    detail = {'aspectIds': ['criterion:condition'], 'criterionIds': ['condition'],
              'missingContent': 'The accepted text does not specify the resolution.',
              'reason': '此缺口由固定检查项的未满足状态汇总；模型说明不作为新增要求或论文事实。'}
    diagnostic = '未核实的完整性诊断（仅供定位，须核对原问题与证据）：' + json.dumps(detail, ensure_ascii=False)
    unique_question = 'What did the cited comparison actually test?'
    data = {'requirements': [{'obligationId': 'test', 'question': question,
                              'completionCriteria': [{'requirement': criterion}]}],
            'questions': {'Q1': question, 'Q2': criterion, 'Q3': diagnostic, 'Q4': unique_question},
            'targets': [{'claim': {'claimId': 'c', 'obligationIds': ['test']},
                         'checks': {'missingQuestionIds': ['Q1', 'Q2', 'Q3', 'Q4'],
                                    'detail': 'Retain the review finding.'}}],
            'sourceRegistry': {'sources': {
                'P1': {'sourceWorkId': 'work', 'sourceVersionId': 'v1', 'title': 'Paper'},
                'P2': {'sourceWorkId': 'work', 'sourceVersionId': 'v2', 'title': 'Paper'}},
                'requirements': [{'requiredSources': {'work': ['P1', 'P2'], 'unavailable': []}}]},
            'comparisonScopes': {'c': {'workId': 'work', 'versionId': 'v1'}},
            'goalsByTarget': {'c': ['test']}}
    before = deepcopy(data)
    compact = compact_inputs(data, question)
    assert data == before and compact['requirements'] == before['requirements']
    assert compact['targets'][0]['checks'] == {'missingQuestionIds': ['Q3', 'Q4'],
                                             'detail': 'Retain the review finding.'}
    assert compact['questions'] == {'Q3': {k: v for k, v in detail.items() if k != 'reason'},
                                    'Q4': unique_question}
    sources = compact['sourceRegistry']['sources']
    scope = compact['comparisonScopes']['c']
    assert sources['P1']['sourceWorkId'] == sources['P2']['sourceWorkId'] == scope['workId']
    assert sources['P1']['sourceVersionId'] == scope['versionId'] != sources['P2']['sourceVersionId']
    assert list(compact['sourceRegistry']['requirements'][0]['requiredSources'].values()) == [['P1', 'P2'], []]


@pytest.mark.parametrize('response_kind', ['empty', 'unchanged', 'changed', 'old_deletion_schema'])
def test_comparison_repair_records_outcomes_and_never_resends_received_batch(response_kind):
    report, verification, ev, opts = comparison_fixture()
    revision = prose('c')
    if response_kind == 'changed':
        revision['body']['prose']['text'] = '该方法在所述条件下评估。'
    elif response_kind == 'old_deletion_schema':
        revision['discardedDraftSpans'] = []
    invoke = Mock(return_value={'content': json.dumps([] if response_kind == 'empty' else [revision]), 'finishReason': 'stop'})
    saved = []
    result = repair_rejected(report, verification, ev, 'Explain the operation.', invoke, json.loads,
        checkpoint=saved.append, **opts)
    assert invoke.call_count == 1
    expected = {'empty': 'not_revised', 'unchanged': 'unchanged', 'changed': 'revised_unverified',
                'old_deletion_schema': 'not_revised'}[response_kind]
    assert saved[-1]['comparisonOutcomeAudit']['0']['targets'] == [{'claimId': 'c', 'status': expected}]
    assert bool(result) == (response_kind == 'changed')
    invoke.reset_mock()
    assert repair_rejected(report, verification, ev, 'Explain the operation.', invoke, json.loads,
        batch_state=saved[-1], **opts) == result
    invoke.assert_not_called()
    from services.deep_research.contracts import DeepResearchError
    with pytest.raises(DeepResearchError):
        repair_rejected(report, verification, ev, 'Explain the operation.', invoke, json.loads,
            batch_state=saved[-1], **{**opts, 'comparison_authoring': False})
    invoke.assert_not_called()
    if result:
        from services.deep_research.verification import verify_claims
        assert not verify_claims(result, ev, Mock(return_value=[]))['accepted']


def test_comparison_source_batches_keep_all_targets_once_and_preserve_joint_goals():
    from services.deep_research.comparison_repair import source_batches
    claims = [{'claimId': x} for x in ('a1', 'b1', 'a2', 'b2', 'joint')]
    context = {'version': 3, 'sources': {'A': {}, 'B': {}}, 'layout': [
        {'source': 'A', 'claimIds': ['a1', 'a2']}, {'source': 'B', 'claimIds': ['b1', 'b2']}]}
    assert source_batches(claims, context) == [['a1', 'a2'], ['b1', 'b2'], ['joint']]
    context['layout'].append({'source': 'B', 'claimIds': ['a1']})
    with pytest.raises(ValueError, match='Ambiguous'):
        source_batches(claims, context)


def test_comparison_outcome_fingerprint_keeps_citation_only_corrections():
    from services.deep_research.comparison_repair import outcome_audit
    old = decode(prose('c'))
    revision = {**deepcopy(old), 'evidenceRefs': ['b']}
    result, audit = outcome_audit({'originals': {'c': old}}, [revision])
    assert result == [revision] and audit['targets'][0]['status'] == 'revised_unverified'


def test_access_level_correction_is_a_real_revision_not_unchanged():
    from services.deep_research.comparison_repair import outcome_audit
    old = decode(prose('c'))
    revision = {**deepcopy(old), 'detailLevel': 'abstract'}
    result, audit = outcome_audit({'originals': {'c': old}}, [revision])
    assert result == [revision] and audit['targets'][0]['status'] == 'revised_unverified'


def test_repaired_measurement_display_rebuilds_only_exact_current_bindings():
    from services.deep_research.comparison_measurement_display import refresh
    from services.deep_research.authored_body import decode
    from services.deep_research.comparison_cells import compile_cells
    from test_deep_research_comparison_wire import fixture as wire_fixture
    plan, payload, _ = wire_fixture()
    claim = decode(compile_cells(payload, plan, max_claims=10)['report']['claims'][0], reasoning=True)
    evidence = list(plan['evidence'].values())
    fixed = refresh(claim, evidence)
    assert fixed['conditions']['原表测量'] == 'Benchmark / Ours-30K：FPS 134'
    assert refresh(fixed, evidence) == fixed
    forged = deepcopy(fixed)
    forged['conditions']['原表测量'] = 'Benchmark / Ours-30K：FPS 999'
    with pytest.raises(ValueError, match='Conflicting'):
        refresh(forged, evidence)
    invalid = deepcopy(claim)
    invalid['tableBindings'][0]['value'] = '999'
    assert refresh(invalid, evidence) == invalid


def test_actual_preparation_preserves_source_permissions_and_goals_with_one_instruction_set():
    report,verification,ev,opts=fixture();snapshot=deepcopy((report,verification,ev,opts))
    old=_prepare_repair(report,verification,ev,'Explain the operation.',max_prompt_bytes=32000,**opts)
    new=_prepare_repair(report,verification,ev,'Explain the operation.',consolidated_instructions=True,**opts)
    for key in ('originals','aliases','allowed','repairPremiseAudit','repairRemovalContractVersion','scopeExpressionContractVersion'):
        assert new[key]==old[key]
    prompt=new['prompt']; packet=prompt.split('Exact repair inputs (goals and metadata, not paper facts):\n')[1].split('\nAllowed evidence IDs')[0]
    data=json.loads(packet)
    assert data['goalsByTarget']=={'c':['o']}
    assert data['targets'][0]['claim']['claimId']=='c'
    assert data['targets'][0]['checks']['reason']=='answer_incomplete'
    assert data['requiredBoundaryIds']==[] and data['sourceRegistry']['sources']
    assert data['outputRowSchema']['body'] and 'discardedDraftSpans' in data['outputRowSchema']
    assert all(e['quote'] in prompt for e in ev if e['evidenceId'] in new['allowed']['c'])
    assert len(prompt.encode())<len(old['prompt'].encode())
    assert new['repairInstructionsContractVersion']==1
    assert snapshot==(report,verification,ev,opts)


def test_shared_repair_input_roundtrips_every_goal_check_and_output_constraint():
    from services.deep_research.shared_strings import unpack
    from services.deep_research.nested_tables import unpack as untables
    report, verification, ev, opts = fixture()
    old = _prepare_repair(report,verification,ev,'Explain the operation.',
                          consolidated_instructions=True,compact_repair_policy=True,**opts)
    new = _prepare_repair(report,verification,ev,'Explain the operation.',
                          consolidated_instructions=True,compact_repair_policy=2,**opts)
    def data(prepared):
        wire = prepared['prompt'].split('Exact repair inputs (goals and metadata, not paper facts):\n',1)[1]
        value = json.JSONDecoder().raw_decode(wire)[0]
        return untables(unpack(value)) if set(value)=={'strings','value'} else value
    before, after = data(old), data(new)
    assert after.pop('comparisonScopes') == {}
    assert before == after
    assert new['compactRepairPolicyVersion']==2 and old['compactRepairPolicyVersion']==1
    assert new['originals']==old['originals']
    assert new['repairPremiseAudit']==old['repairPremiseAudit']


def test_received_repair_cannot_switch_between_shared_and_legacy_input_identity():
    from services.deep_research.contracts import DeepResearchError
    report,verification,ev,opts=fixture();raw=prose('c');raw['evidenceRefs']=['E1'];raw['discardedDraftSpans']=[]
    states=[];invoke=Mock(return_value={'content':json.dumps([raw])})
    args=(report,verification,ev,'Explain the operation.',invoke,json.loads)
    result=repair_rejected(*args,consolidated_instructions=True,compact_repair_policy=2,checkpoint=states.append,**opts)
    assert repair_rejected(*args,consolidated_instructions=True,compact_repair_policy=2,batch_state=states[-1],**opts)==result
    with pytest.raises(DeepResearchError):
        repair_rejected(*args,consolidated_instructions=True,compact_repair_policy=True,batch_state=states[-1],**opts)
    assert invoke.call_count==1


def test_response_is_still_unverified_and_cached_batches_cannot_switch_instruction_policy():
    report,verification,ev,opts=fixture(); raw=prose('c');raw['evidenceRefs']=['E1'];raw['discardedDraftSpans']=[]
    states=[]; invoke=Mock(return_value={'content':json.dumps([raw])})
    args=(report,verification,ev,'Explain the operation.',invoke,json.loads)
    result=repair_rejected(*args,consolidated_instructions=True,checkpoint=states.append,**opts)
    assert result and invoke.call_count==1
    invoke.reset_mock()
    assert repair_rejected(*args,consolidated_instructions=True,batch_state=states[-1],**opts)==result
    invoke.assert_not_called()
    from services.deep_research.contracts import DeepResearchError
    with pytest.raises(DeepResearchError):repair_rejected(*args,batch_state=states[-1],**opts)
    invoke.assert_not_called()
    from services.deep_research.verification import verify_claims
    checker=Mock(return_value=[{'claimId':'c','status':'failed','reason':'Unsupported fixture'}])
    assert not verify_claims(result,ev,checker)['accepted']


@pytest.mark.parametrize('mutation',['retained_deletion','wrong_body','foreign_citation'])
def test_new_instructions_do_not_accept_malformed_edits_or_foreign_evidence(mutation):
    report,verification,ev,opts=fixture(); raw=prose('c');raw['evidenceRefs']=['E1'];raw['discardedDraftSpans']=[]
    if mutation=='retained_deletion':raw['discardedDraftSpans']=['照片']
    if mutation=='wrong_body':raw['text']='top level forbidden'
    if mutation=='foreign_citation':raw['evidenceRefs']=['foreign']
    invoke=Mock(return_value={'content':json.dumps([raw])})
    assert repair_rejected(report,verification,ev,'Explain the operation.',invoke,json.loads,consolidated_instructions=True,**opts)==[]
    invoke.assert_called_once()


@pytest.mark.parametrize('flag',[None,True,False,0,2,1.0,'1'])
def test_only_exact_frozen_server_profile_enables_new_instructions(flag):
    r={'repairInstructionsContractVersion':flag,'verbatimRepairContractVersion':1,
       'factualRepairGoalContractVersion':5,'authoredBodyContractVersion':1,
       'scopeExpressionContractVersion':5,'factualPromptContractVersion':3,
       'factRedraftContractVersion':3,'factualRepairPromptContractVersion':3,
       'state':{'outputKind':'paper_comparison'}}
    assert enabled(r) == (type(flag) is int and flag==2)
    r['repairInstructionsContractVersion']=1;assert enabled(r)
    r['verbatimRepairContractVersion']=0;assert not enabled(r)


@pytest.mark.parametrize('bad',[1,None,'1'])
def test_direct_non_boolean_policy_is_rejected_before_dispatch(bad):
    report,verification,ev,opts=fixture();invoke=Mock()
    with pytest.raises(ValueError):repair_rejected(report,verification,ev,'Explain',invoke,json.loads,consolidated_instructions=bad,**opts)
    invoke.assert_not_called()


def test_unfit_required_quotes_are_not_truncated_or_sent():
    report,verification,ev,opts=fixture()
    ev[0]['quote']='source '+('long original passage '*2000)
    from services.deep_research.contracts import BudgetExhaustedError
    invoke=Mock()
    with pytest.raises(BudgetExhaustedError):
        repair_rejected(report,verification,ev,'Explain',invoke,json.loads,
            consolidated_instructions=True,verified_target_ids=['c'],**opts)
    invoke.assert_not_called()


def test_boundary_ids_and_typed_table_schema_are_preserved_in_exact_input_packet():
    from services.deep_research.repair_instructions import render
    data=dict(question='Compare A and B.',length_contract='',requirements=[{'obligationId':'o'}],
        source_context={'sources':{'P1':{'sourceVersionId':'v1'}}},targets=[{'claimId':'c'}],
        checks={'c':{'reason':'semantic_unresolved'}},questions={},permissions_marker='permissions',
        evidence_marker='evidence',schema={'tableBindings':[]},goals={'c':['o']},hints={'c':'untrusted'},
        intentions={'c':{'scopeDecision':'bounded_inference'}},inference_ids=['c'],required_scope_ids=['c'],has_tables=True)
    before=deepcopy(data);prompt=render(**data)
    packet=json.loads(prompt.split('Exact repair inputs (goals and metadata, not paper facts):\n')[1].split('\nAllowed evidence IDs')[0])
    assert packet['requiredBoundaryIds']==['c'] and packet['reportedToInferenceIds']==['c']
    assert packet['sourceRegistry']==data['source_context'] and packet['outputRowSchema']==data['schema']
    assert 'original rowNumber' in prompt and 'comparison_evidence' in prompt and 'all|exists' in prompt
    assert data==before


def test_policy_server_owned_immutable_and_cannot_be_added_to_legacy_run(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'Explain','deferStart':True,
            'repairInstructionsContractVersion':False},start_async=False)
        assert type(r['repairInstructionsContractVersion']) is int and r['repairInstructionsContractVersion']==5
        ready=deepcopy(r);ready['state']['outputKind']='claim_verification';assert enabled(ready)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(r['runId'],lambda r:{**r,'repairInstructionsContractVersion':False})
        old=deepcopy(r);old.pop('repairInstructionsContractVersion');old.update(runId='legacy',idempotencyKey='old')
        repo.create_run(old)
        with pytest.raises(ValueError,match='Immutable'):repo.update_run('legacy',lambda r:{**r,'repairInstructionsContractVersion':1})
        assert not enabled(repo.require_run('legacy'))
    finally:facade.shutdown()


def test_unified_repair_of_mixed_facts_and_ordinary_advice_preserves_permissions():
    report,checks,ev,opts=fixture()
    advice=deepcopy(report['claims'][0]);advice.update(claimId='advice',kind='proposal')
    report['claims'].append(advice)
    checks['rejected'].append({'claimId':'advice','reason':'internal_reference_in_prose'})
    before=deepcopy((report,checks,ev))
    prepared=_prepare_repair(report,checks,ev,'Explain and suggest reading.',ordinary_advice=True,
        consolidated_instructions=True,max_prompt_bytes=32000,**opts)
    assert set(prepared['originals'])=={'c','advice'}
    assert prepared['allowed']['advice']==prepared['allowed']['c']
    assert prepared['originals']['advice']['kind']=='proposal'
    assert before==(report,checks,ev)
    assert 'Ordinary reading advice remains unexecuted' in prepared['prompt']


@pytest.mark.parametrize('field',['executionSpec','designRole','designContractVersion'])
def test_advice_switch_cannot_admit_experiment_targets_to_unified_point_repair(field):
    report,checks,ev,opts=fixture()
    report['claims'][0].update(kind='proposal',**{field:'experiment'})
    with pytest.raises(ValueError,match='Point-scoped'):
        _prepare_repair(report,checks,ev,'Design an experiment.',ordinary_advice=True,
            consolidated_instructions=True,max_prompt_bytes=32000,**opts)


def test_scope_citation_presentation_keeps_ast_and_text_consistent_through_compaction():
    from test_deep_research_authored_body import boundary
    from services.deep_research.repair import _parse_repair_response
    from services.deep_research.repair_compaction import compact_repairs
    from services.deep_research.scope_expression import materialize
    raw=boundary();raw['body']['boundary']['notEstablished'][0]['quantity']='performance (from E1)'
    report={'claims':[decode(raw)]}
    checks={'accepted':[],'rejected':[{'claimId':'c','reason':'internal_reference_in_prose'}]}
    opts={**options(),'required_scope_ids':['c'],'target_goals':5,'verbatim_repair':True,
          'consolidated_instructions':True,'citation_presentation_version':4}
    prepared=_prepare_repair(report,checks,evidence(),'Compare.',scope_citation_presentation=True,**opts)
    raw['evidenceRefs']=['E1'];raw['discardedDraftSpans']=[]
    scope=[];presentation=[]
    rows=_parse_repair_response(prepared,{'content':json.dumps([raw])},json.loads,presentation,
        strict_response=True,scope_audit=scope)
    assert len(rows)==len(scope)==1
    rebuilt,audit=materialize({**rows[0],'text':'','scopeExpression':scope[0]['expression']},5)
    assert rebuilt==rows[0] and scope[0]['renderedText']==rows[0]['text']
    assert 'from E1' not in rows[0]['text'] and 'cited passage' in rows[0]['text']
    invoke=Mock(side_effect=AssertionError('No model required without a length limit'))
    compacted=compact_repairs(report,rows,[],{'scopeExpressionAudit':{'0':scope}},'Compare.',
        invoke,json.loads,expression_version=5,authored_body=True)
    assert compacted==rows
    invoke.assert_not_called()
    assert presentation and scope[0]['verification']=='unchecked'
    from services.deep_research.verification import verify_claims
    assert not verify_claims(compacted,[])['accepted']


def test_scope_citation_presentation_changes_exact_batch_identity():
    report,checks,ev,opts=fixture();opts.update(consolidated_instructions=True,citation_presentation_version=4)
    raw=prose('c');raw.update(evidenceRefs=['E1'],discardedDraftSpans=[])
    states=[];invoke=Mock(return_value={'content':json.dumps([raw])})
    repair_rejected(report,checks,ev,'Explain.',invoke,json.loads,checkpoint=states.append,**opts)
    invoke.reset_mock()
    from services.deep_research.contracts import DeepResearchError
    with pytest.raises(DeepResearchError):
        repair_rejected(report,checks,ev,'Explain.',invoke,json.loads,batch_state=states[-1],
            scope_citation_presentation=True,**opts)
    invoke.assert_not_called()


@pytest.mark.parametrize('mode',['foreign','literal_symbol'])
def test_structured_scope_presentation_retains_unowned_or_literal_source_symbols(mode):
    from services.deep_research.citation_presentation import normalize_scope_expression
    claim={'claimId':'c','kind':'inference','text':'','conditions':{},'evidenceRefs':['a'],
        'scopeExpression':{'observedSettings':[], 'notEstablished':[{'type':'comparison_evidence',
            'subjects':['A','B'],'quantity':'performance (from E1)'}]}}
    before=deepcopy(claim)
    aliases={'E1':'foreign'} if mode=='foreign' else {'E1':'a'}
    quotes={'E1':'The source symbol E1 denotes energy.'} if mode=='literal_symbol' else {'E1':'A plain passage.'}
    row,_=normalize_scope_expression(claim,aliases,quotes,version=4)
    assert row==before and claim==before


def test_compact_policy_preserves_exact_repair_data_permissions_and_full_scope_grammar():
    report,checks,ev,opts=fixture();opts.update(consolidated_instructions=True,citation_presentation_version=4)
    old=_prepare_repair(report,checks,ev,'Explain.',max_prompt_bytes=32000,**opts)
    new=_prepare_repair(report,checks,ev,'Explain.',max_prompt_bytes=32000,compact_repair_policy=True,**opts)
    for key in ('originals','aliases','allowed','requiredScopeIds','presentationQuotes'):
        assert new.get(key)==old.get(key)
    marker='Exact repair inputs (goals and metadata, not paper facts):\n'
    def data(p):return json.JSONDecoder().raw_decode(p['prompt'].split(marker,1)[1])[0]
    assert data(new)==data(old)
    assert len(new['prompt'].encode())<len(old['prompt'].encode())-1500
    from services.deep_research.authored_body import scope_guidance
    assert scope_guidance(5) in new['prompt']
    assert new['compactRepairPolicyVersion']==1


def test_compact_policy_cannot_reuse_a_previous_pending_or_completed_batch():
    report,checks,ev,opts=fixture();opts.update(consolidated_instructions=True,citation_presentation_version=4)
    raw=prose('c');raw.update(evidenceRefs=['E1'],discardedDraftSpans=[])
    states=[];invoke=Mock(return_value={'content':json.dumps([raw])})
    repair_rejected(report,checks,ev,'Explain.',invoke,json.loads,checkpoint=states.append,**opts)
    invoke.reset_mock()
    from services.deep_research.contracts import DeepResearchError
    with pytest.raises(DeepResearchError):
        repair_rejected(report,checks,ev,'Explain.',invoke,json.loads,batch_state=states[-1],
            compact_repair_policy=True,**opts)
    invoke.assert_not_called()
