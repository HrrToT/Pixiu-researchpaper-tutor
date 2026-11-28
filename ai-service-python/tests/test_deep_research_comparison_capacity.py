from copy import deepcopy

import pytest

from services.deep_research.comparison_capacity import after_synthesis


def candidate():
    return {'stage':'synthesize','claimIsolationContractVersion':1,
            'recommendationReviewContractVersion':1,
            'budget':{'maxModelCalls':18,'modelCalls':7,'reservedModelCalls':1},
            'state':{'outputKind':'paper_comparison','reportBody':{'claims':[
                *[{'claimId':str(i),'kind':'reported','text':'Source-specific point'} for i in range(8)],
                {'claimId':'advice','kind':'proposal','text':'Conditional choice'}]}}}


def test_whole_candidate_uses_both_call_pools_and_keeps_a_final_audit_slot():
    record=candidate();before=deepcopy(record)
    result=after_synthesis(record)
    assert result['remainingModelCalls']==10
    assert result['minimumReviewCalls']==9 and result['minimumWholeAnswerAuditCalls']==1
    assert result['fitsCallLowerBound'] and result['callsBeyondLowerBound']==0
    assert not result['tokensAndTimeFitEstablished'] and not result['scientificApproval']
    assert record==before


def test_shortfall_does_not_remove_points_or_authorize_more_calls():
    record=candidate();record['budget']['reservedModelCalls']=2;before=deepcopy(record)
    result=after_synthesis(record)
    assert not result['fitsCallLowerBound'] and result['minimumAdditionalCalls']==10
    assert record==before and len(record['state']['reportBody']['claims'])==9


def test_unknown_verification_state_cannot_be_mistaken_for_a_fresh_candidate():
    record=candidate();record['stage']='verify'
    assert after_synthesis(record)['status']=='unsupported_policy'


@pytest.mark.parametrize('field,value',[('modelCalls',True),('reservedModelCalls',-1),('modelCalls',19)])
def test_invalid_call_accounting_is_rejected(field,value):
    record=candidate();record['budget'][field]=value
    with pytest.raises(ValueError):after_synthesis(record)


def populated_factual_record():
    from test_deep_research_comparison_intent import record,packets
    from services.deep_research.comparison_cells import compile_cells
    r=record();plan,payload=packets()
    draft=compile_cells(payload,plan,max_claims=8)
    draft['sources']=deepcopy(plan['sources'])
    evidence=[{'evidenceId':f'E{i+1}','sourceWorkId':w,'sourceVersionId':w+'-v1',
               'quote':'A method under stated conditions.','verification':{'literal':'passed'}}
              for i,w in enumerate(('left','right','other'))]
    r.update(runId='r',comparisonPlanningContractVersion=2,comparisonReviewBatchContractVersion=2)
    r['state']={'outputKind':'paper_comparison','comparisonCellDraft':draft,
                'reportBody':draft['report'],'evidence':evidence,
                'plan':[{'obligations':plan['requirements']}]}
    return r


@pytest.mark.parametrize('defect',['legacy','unresolved_cell','empty_cell','semantic_only','proposal'])
@pytest.mark.parametrize('reason', ['numeric_mismatch', 'ambiguous_comparison_baseline'])
def test_initial_audit_deferral_requires_populated_factual_cells_and_an_actionable_hard_error(defect, reason):
    from services.deep_research.comparison_capacity import defer_initial_audit
    r=populated_factual_record();v={'rejected':[{'claimId':'cmp_0_0','reason':reason}]}
    assert defer_initial_audit(r,v)
    if defect=='legacy':r['comparisonReviewBatchContractVersion']=1
    if defect=='unresolved_cell':r['state']['comparisonCellDraft']['layout'][0]['unresolved']=True
    if defect=='empty_cell':r['state']['comparisonCellDraft']['layout'][0]['claimIds']=[]
    if defect=='semantic_only':v['rejected'][0]['reason']='semantic_unresolved'
    if defect=='proposal':r['state']['reportBody']['claims'][0]['kind']='proposal'
    assert not defer_initial_audit(r,v)


@pytest.mark.parametrize(('advice_fields', 'can_defer'), [({}, True), ({'executionSpec': {'groups': []}}, False)])
def test_new_comparison_flow_defers_audit_for_facts_and_ordinary_advice(advice_fields, can_defer):
    from services.deep_research.comparison_capacity import defer_initial_audit

    record = populated_factual_record()
    record.update(recommendationReviewContractVersion=3, recommendationRepairContractVersion=1)
    record['state']['reportBody']['claims'].append({'claimId': 'advice', 'kind': 'proposal', **advice_fields})
    verification = {'rejected': [{'claimId': 'cmp_0_0', 'reason': 'numeric_mismatch'}]}
    assert not defer_initial_audit(record, verification)
    assert defer_initial_audit({**record, 'comparisonRepairFlowContractVersion': 1}, verification) == can_defer
    verification['rejected'][0]['reason'] = 'semantic_unresolved'
    assert not defer_initial_audit({**record, 'comparisonRepairFlowContractVersion': 1}, verification)


@pytest.mark.parametrize('repair_outcome',['changed','empty','unchanged','budget','invalid','unknown','audit_budget'])
def test_production_verify_always_audits_after_deferred_repair_even_when_it_fails(repair_outcome):
    from unittest.mock import Mock,patch
    from services.deep_research.graph import make_verify_node
    from services.deep_research.contracts import BudgetExhaustedError,DeepResearchError
    r=populated_factual_record();claims=deepcopy(r['state']['reportBody']['claims'])
    rejected_id=claims[0]['claimId'];events=[]
    revised={**claims[0],'text':'修订后的明确限定论断。'}
    def update(rid,fn,**kwargs):
        nonlocal r
        r=fn(deepcopy(r));return deepcopy(r)
    def verify(targets,evidence,semantic):
        events.append('verify')
        if len(events)>1:
            if repair_outcome=='unknown':
                raise DeepResearchError('tool_execution_unknown','transport outcome unknown')
            if repair_outcome=='invalid':
                raise DeepResearchError('invalid_verification_response','invalid',{'responseState':'received_invalid'})
            if repair_outcome!='unchanged':return {'accepted':targets,'rejected':[]}
        return {'accepted':[c for c in targets if c['claimId']!=rejected_id],
                'rejected':[{'claimId':rejected_id,'reason':'numeric_mismatch'}]}
    def repair(*args,**kwargs):
        events.append('repair')
        if repair_outcome=='budget':raise BudgetExhaustedError('tokens',100,101)
        return [] if repair_outcome=='empty' else [claims[0] if repair_outcome=='unchanged' else revised]
    def audit(*args,**kwargs):
        events.append('audit')
        assert 'repair' in events
        if repair_outcome=='audit_budget':return {'status':'budget_exhausted','gaps':[{'obligationId':'unverified'}]}
        return {'status':'checked','gaps':[{'obligationId':'still_missing','missingEvidence':'test gap'}]}
    with patch('services.deep_research.repair.repair_rejected',side_effect=repair),patch(
            'services.deep_research.final_coverage.audit_final_answer',side_effect=audit) as audited:
        node=make_verify_node(verify,None,update,llm_invoke=Mock())
        if repair_outcome=='unknown':
            with pytest.raises(DeepResearchError,match='transport outcome unknown'):node({'run_id':'r'})
            assert 'audit' not in events and not r['state'].get('verifiedReport')
            return
        node({'run_id':'r'})
        before=list(events)
        node({'run_id':'r'})
        assert events==before  # Completed checkpoint does not reissue repair/audit.
    assert events[0:2]==['verify','repair'] and events[-1]=='audit' and events.count('audit')==1
    assert r['state']['initialAnswerCoverage']['status']=='deferred_factual_repair'
    result=r['state']['verifiedReport']
    assert result['answerCoverage']['gaps']
    assert result['answerCoverage']['status']==('budget_exhausted' if repair_outcome=='audit_budget' else 'checked')
    accepted_ids={c['claimId'] for c in result['verifiedClaims']}
    assert (rejected_id in accepted_ids)==(repair_outcome in ('changed','audit_budget'))


def test_exhausted_repair_audit_keeps_the_previously_checked_comparison():
    _assert_previously_checked_comparison_survives(6)


def test_local_future_work_repair_still_rechecks_the_claim_and_whole_answer():
    from unittest.mock import Mock, patch
    from services.deep_research.graph import make_verify_node

    record = populated_factual_record()
    record['comparisonLocalFutureWorkRepairVersion'] = 1
    record['state']['reportBody']['comparisonCells'] = {
        key: record['state']['comparisonCellDraft'][key] for key in ('layout', 'sources')}
    claim = record['state']['reportBody']['claims'][0]
    cid = claim['claimId']
    claim['body']['prose']['text'] = '论文将点云压缩列为未来可探索的方向，而非此处已实施的压缩步骤。'
    row = next(row for row in record['state']['evidence'] if row['evidenceId'] in claim['evidenceRefs'])
    row.update(accessLevel='fulltext', quote='It would be interesting to see how compression could be adapted.')
    events = []

    def update(_, mutate, **kwargs):
        nonlocal record
        record = mutate(deepcopy(record))
        return deepcopy(record)

    def verify(targets, evidence, semantic):
        if not events:
            events.append('initial')
            return {'accepted': [c for c in targets if c['claimId'] != cid],
                    'rejected': [{'claimId': cid, 'reason': 'absence_not_established'}]}
        events.append('independent')
        target, = targets
        assert target['text'] == '论文将点云压缩列为未来可探索的方向。'
        assert target['evidenceRefs'] == claim['evidenceRefs']
        return {'accepted': [], 'rejected': [{'claimId': cid, 'reason': 'semantic_unresolved'}]}

    def audit(*args, **kwargs):
        events.append('whole')
        assert not any(c['claimId'] == cid for c in args[3])
        return {'status': 'checked', 'gaps': [{'obligationId': 'required'}]}

    invoke = Mock(side_effect=AssertionError('Local repair must not dispatch generation'))
    with patch('services.deep_research.final_coverage.audit_final_answer', side_effect=audit):
        run = make_verify_node(verify, None, update, llm_invoke=invoke)
        run({'run_id': 'r'})
        run({'run_id': 'r'})
    assert events == ['initial', 'independent', 'whole']
    assert record['state']['repairStatus'] == 'local_candidate'
    assert record['state']['localFutureWorkRepair'] == [
        {'claimId': cid, 'removedSuffix': '，而非此处已实施的压缩步骤', 'scientificApproval': False}]
    invoke.assert_not_called()


@pytest.mark.parametrize('when', ['deferred', 'checked_with_gaps'])
def test_audit_reservation_restricts_optional_repair_budget(monkeypatch, when):
    from unittest.mock import Mock
    from services.deep_research.graph import make_verify_node

    record = populated_factual_record()
    record.update(comparisonPlanningContractVersion=6, comparisonAuthoringContractVersion=16,
                  comparisonAuditEnvelopeContractVersion=10, answerCoherenceContractVersion=2)
    already_checked = when == 'checked_with_gaps'
    if already_checked:
        record['comparisonRepairFlowContractVersion'] = 2
    budget = {'maxTokens': 100000, 'tokens': 78438, 'normalTokens': 42500}
    record['budget'].update(budget)
    calls = []

    def update(_, fn, **kwargs):
        nonlocal record
        record = fn(deepcopy(record))
        return deepcopy(record)

    def verify(claims, evidence, checker):
        reason = 'semantic_unresolved' if already_checked else 'numeric_mismatch'
        return {'accepted': claims[1:], 'rejected': [
            {'claimId': claims[0]['claimId'], 'reason': reason}]}

    def audit(*args, **kwargs):
        assert kwargs['budget']['maxTokens'] == budget['maxTokens']
        if kwargs.get('measure_reservation'):
            calls.append('measure')
            assert len(args[3]) == (len(record['state']['reportBody']['claims']) - int(not already_checked))
            return 17354
        calls.append('audit')
        return {'status': 'checked', 'gaps': [{'obligationId': 'mechanism'}] if already_checked else []}

    def repair(*args, **kwargs):
        calls.append('repair_fit')
        adjusted = kwargs['current_budget']()
        assert adjusted['maxTokens'] == 82646
        assert adjusted['tokens'] == budget['tokens']
        assert kwargs['max_prompt_bytes'] == 0
        return []

    monkeypatch.setattr('services.deep_research.final_coverage.audit_final_answer', audit)
    monkeypatch.setattr('services.deep_research.repair.repair_rejected', repair)
    make_verify_node(verify, None, update, llm_invoke=Mock())({'run_id': 'r'})
    assert calls == (['audit', 'measure', 'repair_fit'] if already_checked
                     else ['measure', 'repair_fit', 'audit'])
    assert record['budget']['maxTokens'] == 100000


def test_named_condition_repair_keeps_the_previously_checked_comparison():
    _assert_previously_checked_comparison_survives(11)


@pytest.mark.parametrize(('input_count', 'permitted'), [(7900, True), (None, True), (7900, False)])
@pytest.mark.parametrize('already_checked', [False, True])
def test_tight_comparison_counts_the_required_audit_before_repair(monkeypatch, input_count, permitted, already_checked):
    from unittest.mock import Mock
    from services.deep_research.contracts import DeepResearchError
    from services.deep_research.graph import make_verify_node
    from services.deep_research.runtime import research_model_options
    from services.deep_research.tools import TrackedLLMInvoker

    record = populated_factual_record()
    record.update(status='running', comparisonPlanningContractVersion=6,
                  comparisonAuthoringContractVersion=16, comparisonAuditEnvelopeContractVersion=21,
                  comparisonRepairFlowContractVersion=3, answerCoherenceContractVersion=2,
                  countedComparisonAuditContractVersion=1, structuredOutputContractVersion=14,
                  openaiResearchModels=['test-review-model', 'test-routine-model'])
    record['budget'].update(maxTokens=100000, tokens=67245, reserveTokens=50000,
                            normalTokens=36905, releasedReserveTokens=19660,
                            maxModelCalls=18, modelCalls=10, reserveModelCalls=5,
                            reservedModelCalls=5, finalizationBudgetVersion=1)
    original_budget = deepcopy(record['budget'])
    calls = []
    unmodified_claims = deepcopy(record['state']['reportBody']['claims'])

    class CountOnly:
        def count_audit_input(self, request):
            assert request.prompt == 'complete existing answer with all cited evidence'
            assert request.extra_body['max_tokens'] == 3500
            calls.append('count')
            return input_count

        def invoke_counted_audit(self, request):
            raise AssertionError('A forecast must not generate')

    def update(_, mutate, **kwargs):
        nonlocal record
        record = mutate(deepcopy(record))
        return deepcopy(record)

    def audit(*args, **kwargs):
        assert kwargs['budget']['maxTokens'] == original_budget['maxTokens']
        if kwargs.get('measure_reservation'):
            assert args[3] == (unmodified_claims if already_checked else unmodified_claims[1:])
            if counter := kwargs.get('reservation_counter'):
                measured = counter('complete existing answer with all cited evidence', 3500)
                return measured if measured is not None else 30000
            return 30000
        assert args[3] == unmodified_claims[1:]
        calls.append('whole_answer')
        return {'status': 'checked', 'verdicts': [], 'gaps': [{'obligationId': 'mechanism'}] if already_checked else []}

    def repair(*args, **kwargs):
        calls.append('repair')
        assert (kwargs['max_prompt_bytes'] > 0) is (input_count is not None)
        assert kwargs['current_budget']()['tokens'] == original_budget['tokens']
        return []

    def verify(claims, evidence, semantic):
        return {'accepted': claims[1:], 'rejected': [
            {'claimId': claims[0]['claimId'], 'reason': 'semantic_unresolved' if already_checked else 'numeric_mismatch'}]}

    forbid_model = Mock(side_effect=AssertionError('The forecast must not reserve a generation'))
    invoker = TrackedLLMInvoker(CountOnly(), forbid_model, forbid_model,
                               run_record_fn=lambda _: record, call_history_fn=lambda _: [],
                               request_options=research_model_options)
    monkeypatch.setattr('services.deep_research.final_coverage.audit_final_answer', audit)
    monkeypatch.setattr('services.deep_research.repair.repair_rejected', repair)
    node = make_verify_node(verify, None, update, llm_invoke=invoker,
                            scope_validator=lambda _, owner: permitted and owner in {'left', 'right', 'other'})
    if not permitted:
        with pytest.raises(DeepResearchError) as error:
            node({'run_id': 'r'})
        assert error.value.code == 'scope_revoked'
        assert calls == (['whole_answer'] if already_checked else [])
        forbid_model.assert_not_called()
        return
    node({'run_id': 'r'})
    node({'run_id': 'r'})
    assert calls == (['whole_answer', 'count', 'repair'] if already_checked
                     else ['count', 'repair', 'whole_answer'])
    assert record['state']['verifiedReport']['verifiedClaims'] == unmodified_claims[1:]
    assert record['budget'] == original_budget
    forbid_model.assert_not_called()


@pytest.mark.parametrize('phase', ['initial', 'deferred', 'repaired'])
@pytest.mark.parametrize('mutate_evidence', [False, True])
@pytest.mark.parametrize('audit_version', [18, 19])
def test_comparison_audit_recovery_keeps_original_admission_budget(monkeypatch, phase, mutate_evidence, audit_version):
    from unittest.mock import Mock
    from services.deep_research.contracts import DeepResearchError
    from services.deep_research.graph import make_verify_node

    record = populated_factual_record()
    record.update(comparisonPlanningContractVersion=6, comparisonAuthoringContractVersion=16,
                  comparisonAuditEnvelopeContractVersion=audit_version, answerCoherenceContractVersion=2,
                  comparisonRepairFlowContractVersion=1)
    record['budget'].update(maxTokens=100000, tokens=72000)
    from services.deep_research.authored_body import decode
    original = decode(record['state']['reportBody']['claims'][0])
    revised = {**original, 'text': 'Revised with a verified condition.'}
    budgets = []

    def update(_, change, **kwargs):
        nonlocal record
        record = change(deepcopy(record))
        return deepcopy(record)

    def verify(claims, evidence, semantic):
        if phase == 'repaired':
            if claims == [revised]:
                return {'accepted': claims, 'rejected': []}
            return {'accepted': claims[1:], 'rejected': [
                {'claimId': original['claimId'], 'reason': 'semantic_unresolved'}]}
        if phase == 'deferred':
            return {'accepted': claims[1:], 'rejected': [
                {'claimId': claims[0]['claimId'], 'reason': 'numeric_mismatch'}]}
        return {'accepted': claims, 'rejected': []}

    def audit(*args, budget, **kwargs):
        assert kwargs.get('share_comparison_evidence_overlaps', False) == (audit_version == 19)
        if kwargs.get('measure_reservation'):
            return 8000
        if phase == 'repaired' and revised not in args[3]:
            return {'status': 'checked', 'gaps': [], 'verdicts': []}
        budgets.append(budget['tokens'])
        if len(budgets) == 1:
            record['budget']['tokens'] += 6000
            raise RuntimeError('interrupted after settlement')
        return {'status': 'checked', 'gaps': [], 'verdicts': []}

    monkeypatch.setattr('services.deep_research.final_coverage.audit_final_answer', audit)
    replacements = [revised] if phase == 'repaired' else []
    monkeypatch.setattr('services.deep_research.repair.repair_rejected', Mock(return_value=replacements))
    node = make_verify_node(verify, None, update, llm_invoke=Mock())
    with pytest.raises(RuntimeError, match='after settlement'):
        node({'run_id': 'r'})
    assert record['state']['comparisonAnswerAuditInputs'][phase]['budget']['tokens'] == 72000
    assert record['budget']['tokens'] == 78000

    if mutate_evidence:
        record['state']['evidence'][0]['quote'] += ' Changed after settlement.'
        with pytest.raises(DeepResearchError) as caught:
            node({'run_id': 'r'})
        assert caught.value.code == 'comparison_answer_audit_inputs_changed'
        assert budgets == [72000]
    else:
        node({'run_id': 'r'})
        assert budgets == [72000, 72000]
        assert record['state']['verifiedReport']['answerCoverage']['status'] == 'checked'


def _assert_previously_checked_comparison_survives(authoring_version):
    from unittest.mock import Mock, patch
    from services.deep_research.answer_coherence import identity
    from services.deep_research.comparison_presentation import audit_digest
    from services.deep_research.graph import make_verify_node

    r = populated_factual_record()
    r.update(comparisonPlanningContractVersion=6, comparisonAuthoringContractVersion=authoring_version)
    from services.deep_research.authored_body import decode
    claims = [decode(c) for c in r['state']['reportBody']['claims']]
    rejected_id = claims[0]['claimId']
    first_check = {'accepted': claims[1:], 'rejected': [
        {'claimId': rejected_id, 'reason': 'semantic_unresolved'}]}
    revision = {**claims[0], 'text': 'Revised with scope.'}
    verify = Mock(side_effect=[first_check, {'accepted': [revision], 'rejected': []}])
    limit = {'kind': 'coveragePromptBytes', 'limit': 10, 'used': 2000}
    audits = []

    def audit(rid, question, plan, accepted, *args, comparison_cells, **kwargs):
        if audits:
            assert revision['claimId'] in {claim['claimId'] for claim in accepted}
            return {'status': 'budget_exhausted', 'budgetLimit': limit}
        checked = {'status': 'checked', 'comparisonPresentationDigest': audit_digest(comparison_cells, accepted),
                   'answerCoherence': {'contractVersion': 1, 'status': 'checked', 'coherent': True,
                                       'issues': [], 'answerDigest': identity(question, accepted)},
                   'gaps': [{'obligationId': 'mechanism', 'missingEvidence': 'Still missing.'}]}
        audits.append(checked)
        return checked

    def update(rid, fn, **kwargs):
        nonlocal r
        r = fn(deepcopy(r))
        return deepcopy(r)

    with patch('services.deep_research.repair.repair_rejected', return_value=[revision]), patch(
            'services.deep_research.final_coverage.audit_final_answer', side_effect=audit) as reviewer:
        make_verify_node(verify, None, update, llm_invoke=Mock())({'run_id': 'r'})

    state = r['state']
    assert reviewer.call_count == 2
    assert state['verifiedReport']['verifiedClaims'] == first_check['accepted']
    assert state['verifiedReport']['answerCoverage'] == audits[0]
    assert state['repairVerification']['accepted'] != first_check['accepted']
    assert state['repairReleaseDeferred'] == {'status': 'budget_exhausted', 'budgetLimit': limit}
