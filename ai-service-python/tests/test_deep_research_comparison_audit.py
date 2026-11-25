from copy import deepcopy
import json
from unittest.mock import Mock, patch

import pytest

from services.deep_research.final_coverage import audit_final_answer
from services.deep_research.comparison_audit import renderer
from services.deep_research.shared_strings import unpack
from services.deep_research.nested_tables import unpack as untables
from test_deep_research_request_coverage import QUESTION, PLAN, CLAIMS, EVIDENCE, response


MARKER = 'Complete exact decision inputs (evidence detects omissions, never replaces answer):\n'


def decode(prompt):
    value = json.JSONDecoder().raw_decode(prompt.split(MARKER, 1)[1])[0]
    return untables(unpack(value)) if set(value) == {'strings', 'value'} else value


def presentation(version=3):
    return {'version':version, 'sources':{'P1':{'title':'Paper', 'workId':'paper', 'versionId':'v'}},
            'jointGoals':[], 'layout':[{'source':'P1', 'obligationId':'o', 'question':QUESTION,
                                       'axisId':'axis', 'axisTitle':'结果与条件', 'claimIds':['a','b']}]}


def audit(mutation=None, evidence=None, wire_mode=None, explicit_shapes=False, compact_layout=False,
          compact_checks=False, budget=None, fit_compact_budget=False, dispatches=None,
          comparison=None, claims=CLAIMS, require_joint=False, compact_instructions=False, bounded_packet=False,
          rendered_packet=False, plan=PLAN, local_check_fields=False, label_checks=False, inline_limits=False,
          require_covered_bindings=False):
    evidence = deepcopy(EVIDENCE if evidence is None else evidence)
    sent = []
    def invoke(rid, node, prompt, options, **kwargs):
        assert node == 'verify_answer_coverage' and kwargs == {'use_reserve':True}
        data = decode(prompt); sent.append(data)
        if dispatches is not None:
            dispatches.append((len(prompt.encode('utf-8')), options['max_tokens']))
        if mutation == 'admission':
            from services.deep_research.contracts import BudgetExhaustedError
            raise BudgetExhaustedError('tokens', 100, 101)
        rows = response(data['requirements'])
        for row, obligation in zip(rows, data['requirements']):
            for check, required in zip(row['checks'], obligation['checks']):
                if required.get('responseType') == 'limitation':
                    if inline_limits:
                        excerpt = ('not in answer' if mutation == 'inline_wrong' else None if mutation == 'inline_null' else CLAIMS[1]['text'])
                        if mutation != 'inline_omitted':
                            check['bindings'] = [{**binding, 'excerpt':excerpt if binding['claimId'] == 'b' else None}
                                                 for binding in check['bindings']]
                    else:
                        check['limitSpans'] = [{'claimId':'b','field':'text','excerpt':CLAIMS[1]['text']}]
        check = rows[0]['checks'][0]
        if mutation == 'foreign':check['bindings'] = [{'claimId':'foreign','field':'text'}]
        elif mutation == 'metadata':check['bindings'] = [{'claimId':'a','field':'table'}]
        elif mutation == 'drop':rows[0]['checks'].pop()
        elif mutation == 'extra':check['unrequested'] = True
        elif mutation == 'partial':check.update(status='partial',reason='The answer is only partial.')
        elif mutation in ('whole_unbound_covered', 'whole_unbound_missing'):
            rows[-1]['checks'][0].update(bindings=[], status=mutation.rsplit('_', 1)[1])
        elif mutation == 'limit':rows[0]['checks'][1]['limitSpans'][0]['excerpt'] = 'not in answer'
        elif mutation == 'omit_limit':rows[0]['checks'][1].pop('limitSpans')
        elif mutation == 'omit_row':rows.pop()
        elif mutation == 'foreign_obligation':rows[0]['obligationId'] = 'foreign'
        elif mutation == 'foreign_check':rows[0]['checks'][0]['checkId'] = rows[1]['checks'][0]['checkId']
        elif mutation == 'waive':rows[0] = {'obligationId':rows[0]['obligationId'], 'notRequired':{
            'reason':'The actual answer requirement is allegedly unnecessary.',
            'requestExcerpt':QUESTION,'bindings':[{'claimId':'a','field':'text'}]}}
        if compact_checks:
            assert '"reason":"1-800 characters"' not in prompt
            for row in rows:
                for ordinary_check in row.get('checks', []):
                    ordinary_check.pop('reason')
            if mutation == 'legacy_reason':
                check['reason'] = 'Unexpected free-form explanation.'
        if require_covered_bindings:
            assert 'Never return covered with bindings:[].' in prompt
        rows.append({'auditType':'answer_coherence','coherent':mutation != 'incoherent',
            'issues':[] if mutation != 'incoherent' else [{'kind':'contradiction',
              'bindings':[{'claimId':'a','field':'text'}], 'reason':'Fixture joint contradiction.'}]})
        if wire_mode is not None:
            from services.deep_research.structured_output import normalize
            if wire_mode=='object_v1':
                if compact_instructions and not rendered_packet:
                    assert '"items":ROWS,"auditType":"answer_coherence"' in prompt
                elif not rendered_packet:
                    assert 'Root coherence fields (never items)' in prompt
                reply = {'content':json.dumps({'items':rows[:-1],**rows[-1]})}
                if mutation == 'truncated':
                    reply['finishReason'] = 'length'
                return normalize(node,reply,comparison_audit_envelope=True)
            assert 'Return ONLY {"items":[ROWS]}' in prompt and 'INSIDE items (NEVER at root)' in prompt
            data={'items':rows} if wire_mode=='valid' else {'items':rows[:-1],**rows[-1]}
            return normalize(node,{'content':json.dumps(data)})
        return {'content':json.dumps(rows)}
    before = deepcopy((plan, claims, evidence))
    comparison = presentation() if comparison is None else deepcopy(comparison)
    if explicit_shapes:
        comparison['checkOutputShapeVersion'] = 1
    result = audit_final_answer('r',QUESTION,plan,claims,evidence,invoke,json.loads,
        request_contract=5, diagnostics=True,literal_dimensions=True, coherence=True,
        task_sources=True,request_semantics=2,binding_catalog=True,scoped_catalog=True,
        shared_decision_inputs=True,shared_evidence_context=True,consolidated_instructions=True,
        literal_limits=True,comparison_cells=comparison,compact_comparison_layout=compact_layout,
        compact_comparison_checks=compact_checks,budget=budget,
        fit_compact_comparison_budget=fit_compact_budget,
        require_joint_conclusions=require_joint,
        compact_comparison_instructions=compact_instructions,
        bounded_comparison_packet=bounded_packet,
        rendered_comparison_packet=rendered_packet,
        local_comparison_check_fields=local_check_fields,
        label_comparison_checks=label_checks,
        inline_comparison_limits=inline_limits,
        require_covered_bindings=require_covered_bindings,
        **({'comparison_audit_envelope':True} if wire_mode=='object_v1' else {}))
    assert before == (plan, claims, evidence)
    return result, sent


def test_whole_answer_requires_bound_accepted_fields_for_covered():
    options = dict(wire_mode='object_v1', explicit_shapes=True, compact_layout=True,
                   compact_checks=True, compact_instructions=True, bounded_packet=True,
                   rendered_packet=True, local_check_fields=True, label_checks=True, inline_limits=True,
                   require_covered_bindings=True)
    invalid, sent = audit('whole_unbound_covered', **options)
    assert len(sent) == 1
    assert invalid['status'] == 'invalid_response'
    assert invalid['requestResponseErrors'] == [
        {'code': 'unbound_covered_check', 'obligationId': 'answer_scope', 'checkId': 'request'}]
    verdicts = {row['obligationId']: row for row in invalid['verdicts']}
    assert verdicts['o']['status'] == 'covered'
    assert verdicts['answer_scope']['aspects'][0]['status'] == 'partial'
    assert verdicts['answer_scope']['aspects'][0]['bindings'] == []

    missing, _ = audit('whole_unbound_missing', **options)
    assert missing['status'] == 'checked'
    assert 'requestResponseErrors' not in missing
    assert any(gap['obligationId'] == 'answer_scope' for gap in missing['gaps'])


def test_full_question_checks_claims_conditions_and_required_context_survive_one_bundle():
    ev = deepcopy(EVIDENCE)
    ev[0]['sourceContext']='Critical surrounding condition. '+ev[0]['quote']+' Restriction.'
    result, sent = audit(evidence=ev)
    assert result['status'] == 'checked' and not result['gaps']
    assert len(sent) == 1
    data = sent[0]
    assert data['question'] == QUESTION
    assert [(c['text'],c['conditions']) for c in data['claims']] == [(c['text'],c['conditions']) for c in CLAIMS]
    assert len(data['evidence']) == 1 and data['evidence'][0]['quote'] == ev[0]['quote']
    from services.deep_research.selection import surrounding_context
    assert data['evidence'][0]['sourceContext'] == surrounding_context(ev[0])
    assert 'Critical surrounding condition.' in data['evidence'][0]['sourceContext']['before']
    assert data['requirements'][0]['checks'][1]['requirement'] == PLAN[0]['obligations'][0]['completionCriteria'][1]['requirement']
    assert data['comparisonPresentation']['version'] == 3 and data['bindingCatalog']


@pytest.mark.parametrize('mutation',['foreign','metadata','drop','extra','waive'])
def test_compact_input_keeps_existing_strict_coverage_rejection(mutation):
    result,sent = audit(mutation)
    assert sent and result['status'] == 'invalid_response' and result['gaps']


@pytest.mark.parametrize('mutation',['partial','incoherent','limit'])
def test_negative_decisions_are_not_promoted(mutation):
    result,sent = audit(mutation)
    assert sent and result['gaps']
    if mutation == 'incoherent':assert result['answerCoherence']['coherent'] is False
    if mutation == 'limit':
        assert any(v.get('limitAudits') and any(a['errors'] for a in v['limitAudits']) for v in result['verdicts'])


def test_oversized_required_context_stops_without_adapter_call():
    ev = deepcopy(EVIDENCE); ev[0]['quote'] = 'unique full quote '*3000
    result, sent = audit(evidence=ev)
    assert not sent and result['status'] == 'budget_exhausted'
    assert result['budgetLimit']['kind'] == 'coveragePromptBytes'


def test_missing_process_links_are_empty_only_for_an_explicit_unbound_gap():
    from services.deep_research.request_coverage import normalize

    requirement = {'obligationId':'o', 'question':QUESTION, 'purpose':'answer_requirement',
                   'checks':[{'checkId':'method','requirement':'解释步骤','processRequired':True}]}
    check = {'checkId':'method','status':'missing','bindings':[]}
    reply = [{'obligationId':'o','checks':[check]}]
    args = dict(process_explanations=True, compact_checks=True)
    assert normalize(reply, [requirement], **args) is None
    results = normalize(reply, [requirement], empty_missing_process=True, **args)
    assert results[0]['status']=='missing' and results[0]['processAudits'][0]['links']==[]
    assert 'processLinks' not in check
    for status in ('partial','covered'):
        check.update(status=status, bindings=[{'claimId':'a','field':'text'}])
        assert normalize(reply, [requirement], empty_missing_process=True, **args) is None


def test_audit_can_show_exact_display_paper_of_each_accepted_claim():
    comparison = presentation()
    comparison['sources']['P2'] = {'title':'Second paper','workId':'second','versionId':'v2'}
    comparison['layout'][0]['claimIds'] = ['a']
    comparison['layout'].append({**comparison['layout'][0], 'source':'P2','claimIds':['b']})
    prompt = renderer(QUESTION, [], CLAIMS, {}, comparison, source_labels=True)([])
    assert decode(prompt)['paperByClaim'] == {'a':'Paper','b':'Second paper'}
    assert 'Titles identify sources only' in prompt
    inline = decode(renderer(QUESTION, [], CLAIMS, {}, comparison,
                             source_labels=True, inline_paper_labels=True)([]))
    assert [claim['displayedUnderPaper'] for claim in inline['claims']] == ['Paper','Second paper']
    assert [{k: v for k, v in claim.items() if k != 'displayedUnderPaper'} for claim in inline['claims']] == CLAIMS
    assert 'paperByClaim' not in inline
    scoped = renderer(QUESTION, [], CLAIMS, {}, comparison, source_labels=True,
                       inline_paper_labels=True, scoped_coherence=True)([])
    assert decode(scoped) == inline
    assert 'incompatible assertions about the same entity under the same scope' in scoped
    assert 'explicit cross-paper assertion inconsistent with a cell' in scoped


def test_shorter_audit_keeps_decision_packet_and_coverage_validators():
    options = dict(wire_mode='object_v1', explicit_shapes=True, compact_layout=True, compact_checks=True)
    prior_calls, new_calls = [], []
    prior, prior_packets = audit(**options, dispatches=prior_calls)
    current, new_packets = audit(**options, compact_instructions=True, dispatches=new_calls)
    assert current == prior
    assert new_packets == prior_packets
    assert new_calls[0][0] < prior_calls[0][0]
    assert new_calls[0][1] == prior_calls[0][1]
    refused, _ = audit('foreign', **options, compact_instructions=True)
    assert refused['status'] != 'checked' or refused['gaps']


def test_bounded_comparison_preserves_exact_checks_cited_context_and_release_digest():
    options = dict(wire_mode='object_v1', explicit_shapes=True, compact_layout=True, compact_checks=True,
                   compact_instructions=True)
    source = deepcopy(EVIDENCE)
    source[0]['sourceContext'] = 'Required condition. ' + source[0]['quote'] + ' Adjacent restriction.'
    calls, compact_calls = [], []
    prior, before = audit(**options, evidence=source, dispatches=calls)
    current, after = audit(**options, evidence=source, dispatches=compact_calls, bounded_packet=True)
    assert compact_calls[0][0] < calls[0][0]
    assert prior == current
    for field in ('question','requirements','claims','evidence','bindingCatalog','extraCheckFields'):
        assert before[0][field] == after[0][field]
    assert before[0]['comparisonPresentation']['layout'] == after[0]['comparisonPresentation']['layout']
    assert 'renderedTextSha256' in before[0]['comparisonPresentation']['table']
    assert 'renderedTextSha256' not in after[0]['comparisonPresentation']['table']


def test_rendered_comparison_audit_preserves_claims_citations_conditions_and_bindings():
    options = dict(wire_mode='object_v1', explicit_shapes=True, compact_layout=True,
                   compact_checks=True, compact_instructions=True, bounded_packet=True)
    source = deepcopy(EVIDENCE)
    source[0]['sourceKind'] = 'task_paper'
    source[0]['sourceContext'] = 'Critical condition. ' + source[0]['quote'] + ' Adjacent restriction.'
    before, [old] = audit(**options, evidence=source)
    after, [new] = audit(**options, evidence=source, rendered_packet=True)
    assert before == after and after['status'] == 'checked'
    assert {k: v for k, v in old['evidence'][0].items() if k != 'source'} == {
        k: v for k, v in new['evidence'][0].items() if k != 'source'}
    alias = new['evidence'][0]['source']
    assert new['comparisonPresentation']['sources'][alias]['workId'] == old['evidence'][0]['source']
    assert 'sourceAccessRecords' in old['metadata']
    assert 'sourceAccessRecords' not in new['metadata']
    assert old['metadata']['sourceAccessSummary'] == new['metadata']['sourceAccessSummary']
    assert new['bindingCatalog']['catalogs'] == old['bindingCatalog']['catalogs']
    assert [(c['claimId'], c['text'], c['conditions'], c['evidenceRefs']) for c in new['claims']] == [
        (c['claimId'], c['text'], c['conditions'], c['evidenceRefs']) for c in old['claims']]
    rejected, _ = audit('foreign', **options, evidence=source, rendered_packet=True)
    assert rejected['status'] != 'checked' or rejected['gaps']


def test_rendered_limit_output_is_declared_on_its_check_and_still_required():
    options = dict(wire_mode='object_v1', explicit_shapes=True, compact_layout=True,
                   compact_checks=True, compact_instructions=True, bounded_packet=True, rendered_packet=True)
    prior, [old] = audit(**options)
    after, [new] = audit(**options, local_check_fields=True)
    assert after == prior
    assert 'extraCheckFields' not in new
    for old_row, new_row in zip(old['requirements'], new['requirements'], strict=True):
        for old_check, new_check in zip(old_row['checks'], new_row['checks'], strict=True):
            required = old['extraCheckFields'].get(old_row['obligationId'], {}).get(old_check['checkId'])
            assert new_check.get('requiredOutput') == required
            assert {k: v for k, v in new_check.items() if k != 'requiredOutput'} == old_check
    rejected, _ = audit('omit_limit', **options, local_check_fields=True)
    assert rejected['status'] == 'invalid_response'
    assert any(row.get('missingFields') == ['limitSpans'] for row in rejected['requestResponseErrors'])
    limitation = next(c for c in rejected['verdicts'][0]['criteria'] if c['responseType'] == 'limitation')
    assert limitation['status'] == 'partial'
    from services.deep_research.answer_coherence import publication_release
    assert rejected['answerCoherence']['coherent'] is True
    assert publication_release(rejected, QUESTION, CLAIMS)['reason'] == 'limit_proof_missing'
    invalid_span, _ = audit('limit', **options, local_check_fields=True)
    assert invalid_span['gaps']


def test_short_audit_labels_restore_full_review_without_approving_missing_rows():
    options = dict(wire_mode='object_v1', explicit_shapes=True, compact_layout=True,
                   compact_checks=True, compact_instructions=True, bounded_packet=True,
                   rendered_packet=True, local_check_fields=True)
    original, [old] = audit(**options)
    result, [new] = audit(**options, label_checks=True)
    assert result == original
    assert new['requirements'][0]['obligationId'] == 'R1'
    assert new['requirements'][0]['checks'][0]['checkId'] == 'K1'
    assert len(old['requirements']) == len(new['requirements'])
    for mutation in ('omit_row', 'drop', 'foreign_obligation', 'foreign_check', 'truncated'):
        invalid, _ = audit(mutation, **options, label_checks=True)
        assert invalid['status'] == 'invalid_response'
        assert not invalid['verdicts']


def test_inline_comparison_limit_uses_exact_answer_substring_and_preserves_negative_decisions():
    options = dict(wire_mode='object_v1', explicit_shapes=True, compact_layout=True,
                   compact_checks=True, compact_instructions=True, bounded_packet=True,
                   rendered_packet=True, local_check_fields=True, label_checks=True)
    checked, _ = audit(**options)
    inline, [packet] = audit(**options, inline_limits=True)
    assert checked == inline
    assert all('limitSpans' not in check.get('requiredOutput', [])
               for row in packet['requirements'] for check in row['checks'])
    for mutation in ('inline_wrong', 'inline_null', 'inline_omitted'):
        rejected, _ = audit(mutation, **options, inline_limits=True)
        criterion = next(c for c in rejected['verdicts'][0]['criteria'] if c['responseType'] == 'limitation')
        assert criterion['status'] == 'partial'
        assert rejected['gaps']
        if mutation == 'inline_omitted':
            assert rejected['status'] == 'invalid_response'


def test_compact_audit_reallocates_only_output_capacity_before_dispatch():
    options = dict(wire_mode='object_v1', explicit_shapes=True, compact_layout=True, compact_checks=True)
    roomy = []
    with patch('services.deep_research.final_coverage.coverage_output_tokens', return_value=5402):
        reference, inputs = audit(**options, dispatches=roomy, fit_compact_budget=True)
        size, output = roomy[0]
        assert output == 5402
        budget = {'maxTokens': size + 1024 + 3500, 'maxModelCalls': 1, 'reserveModelCalls': 1}
        legacy, sent = audit(**options, budget=budget)
        assert legacy['status'] == 'budget_exhausted' and not sent
        limited = []
        result, sent = audit(**options, budget=budget, fit_compact_budget=True, dispatches=limited)
        assert sent == inputs and result == reference
        assert limited == [(size, 3500)]
        denied, sent = audit(**options, budget={**budget, 'maxTokens': budget['maxTokens'] - 1}, fit_compact_budget=True)
        assert denied['status'] == 'budget_exhausted' and not sent
        truncated, sent = audit('truncated', **options, budget=budget, fit_compact_budget=True)
        assert truncated['status'] == 'invalid_response' and len(sent) == 1
        refused, sent = audit('admission', **options, budget=budget, fit_compact_budget=True)
        assert refused['status'] == 'budget_exhausted' and len(sent) == 1


def test_small_rendered_audit_can_fit_short_output_and_still_denies_truncation():
    options = dict(wire_mode='object_v1', explicit_shapes=True, compact_layout=True, compact_checks=True,
                   fit_compact_budget=True, compact_instructions=True, bounded_packet=True, rendered_packet=True)
    plan = deepcopy(PLAN)
    for item in plan:
        for obligation in item['obligations']:
            for criterion in obligation.get('completionCriteria', []):
                if criterion['responseType'] == 'limitation':
                    criterion['responseType'] = 'explanation'
    options['plan'] = plan
    roomy = []
    reference, packets = audit(**options, dispatches=roomy)
    size, _ = roomy[0]
    budget = {'maxTokens': size + 1024 + 1200, 'maxModelCalls': 1, 'reserveModelCalls': 1}
    limited = []
    result, sent = audit(**options, budget=budget, dispatches=limited)
    assert sent == packets and result == reference and limited == [(size, 1200)]
    truncated, sent = audit('truncated', **options, budget=budget)
    assert truncated['status'] == 'invalid_response' and len(sent) == 1


def test_joint_deliverable_cannot_be_closed_by_checked_paper_cells():
    comparison = presentation()
    comparison['jointGoals'] = [{'obligationId': 'o', 'question': QUESTION}]
    claims = [{**c, 'obligationIds': ['o']} for c in CLAIMS]
    options = dict(wire_mode='object_v1', compact_checks=True, comparison=comparison, claims=claims)
    prior, _ = audit(**options)
    assert prior['status'] == 'checked' and not prior['gaps']
    guarded, _ = audit(**options, require_joint=True)
    assert guarded['status'] == 'checked' and guarded['verdicts'] == prior['verdicts']
    assert guarded['gaps'] == [{'obligationId':'o', 'question':QUESTION, 'stage':'answer',
                                'missingJointConclusion':True,
                                'missingEvidence':'尚未形成通过核验的联合比较结论'}]
    comparison['layout'][0]['claimIds'].remove('b')
    delivered, _ = audit(**options, require_joint=True)
    assert delivered['status'] == 'checked' and not delivered['gaps']


def test_numeric_joint_claim_cannot_satisfy_separate_advice_delivery():
    comparison = presentation()
    comparison['layout'][0]['claimIds'] = []
    comparison['jointGoals'] = [{'obligationId': 'o', 'question': QUESTION}]
    comparison['jointDeliverables'] = {'o': [
        {'kind':'matched_example','requirement':'给出同口径数字对照。'},
        {'kind':'conditional_advice','requirement':'给出有条件的建议。'},
    ]}
    claims = [{**CLAIMS[0], 'obligationIds': ['o']}, CLAIMS[1]]
    options = dict(wire_mode='object_v1', compact_checks=True, comparison=comparison, require_joint=True)
    checked, _ = audit(**options, claims=claims)
    assert checked['status'] == 'checked'
    assert checked['gaps'][0]['missingAspects'] == ['给出有条件的建议。']
    claims = [claims[0], {**claims[1], 'kind':'suggestion','obligationIds':['o']}]
    completed, _ = audit(**options, claims=claims)
    assert completed['status'] == 'checked' and completed['gaps'] == []


@pytest.mark.parametrize('mode',['valid','root_coherence'])
def test_actual_native_envelope_accepts_only_coherence_inside_items(mode):
    result,sent=audit(wire_mode=mode)
    assert len(sent)==1
    if mode=='valid':assert result['status']=='checked' and not result['gaps']
    else:assert result['status']=='invalid_response' and result['gaps']


@pytest.mark.parametrize('mutation',[None,'foreign','metadata','drop','extra','waive','partial','incoherent','limit'])
def test_object_envelope_keeps_all_existing_content_checks(mutation):
    result,sent=audit(mutation,wire_mode='object_v1')
    assert len(sent)==1
    if mutation is None:assert result['status']=='checked' and not result['gaps']
    else:assert result['gaps']
    if mutation=='incoherent':assert result['answerCoherence']['coherent'] is False


@pytest.mark.parametrize('mutation', [None, 'legacy_reason', 'truncated', 'foreign', 'drop',
                                     'limit', 'partial', 'incoherent', 'waive'])
def test_compact_checks_preserve_strict_audit_without_free_form_check_reasons(mutation):
    result, [inputs] = audit(mutation, wire_mode='object_v1', explicit_shapes=True,
                             compact_layout=True, compact_checks=True)
    assert any('limitSpans' in fields for checks in inputs['extraCheckFields'].values()
               for fields in checks.values())
    if mutation is None:
        assert result['status'] == 'checked' and not result['gaps']
        assert all(not row['requestCheckReasons'] for row in result['verdicts'])
    else:
        assert result['gaps']
        if mutation in ('legacy_reason', 'truncated', 'foreign', 'drop', 'waive'):
            assert result['status'] == 'invalid_response'


@pytest.mark.parametrize('version',[1,2])
def test_historical_layouts_keep_their_original_audit_input(version):
    invoke = Mock(return_value={'content':'[]'})
    with patch('services.deep_research.comparison_audit.renderer',side_effect=AssertionError('New path selected')):
        audit_final_answer('r',QUESTION,PLAN,CLAIMS,EVIDENCE,invoke,json.loads,
            request_contract=5,diagnostics=True,shared_evidence_context=True,
            shared_decision_inputs=True,consolidated_instructions=True,comparison_cells=presentation(version))
    assert invoke.call_count == 1 and MARKER not in invoke.call_args.args[2]


def test_renderer_copies_mutable_inputs_and_rejects_legacy_layout():
    points=deepcopy(CLAIMS);meta=presentation()
    render=renderer(QUESTION,[],points,{},meta)
    points[0]['text']='later mutation';meta['layout'][0]['axisTitle']='later mutation'
    data=decode(render([]))
    assert data['claims'][0]['text']==CLAIMS[0]['text']
    assert data['comparisonPresentation']['layout'][0]['axisTitle']=='结果与条件'
    with pytest.raises(ValueError):renderer(QUESTION,[],CLAIMS,{},presentation(2))


def test_compact_input_preserves_decision_inputs_and_verdict():
    options = {'wire_mode': 'object_v1', 'explicit_shapes': True}
    legacy_result, [legacy] = audit(**options)
    compact_result, [compact] = audit(**options, compact_layout=True)
    assert compact_result == legacy_result
    for key in ('question', 'requirements', 'claims', 'evidence', 'bindingCatalog'):
        if key in legacy:
            assert compact[key] == legacy[key]
    assert compact['metadata'] == {
        key: value for key, value in legacy['metadata'].items()
        if key not in {'requestSemanticsContractVersion', 'identificationLocatorContractVersion',
                       'taskSourceAccessContractVersion', 'answerBindingCatalogVersion'}
    }
    legacy_presentation = legacy['comparisonPresentation']
    compact_presentation = compact['comparisonPresentation']
    assert compact_presentation == {
        **legacy_presentation,
        'layout': [{key: row[key] for key in ('axisId', 'axisTitle', 'source', 'claimIds')}
                   for row in legacy_presentation['layout']],
    }
    for row in legacy['checkOutputShapes']:
        added = compact['extraCheckFields'].get(row['obligationId'], {})
        for check in row['checks']:
            assert check['fields'][4:] == added.get(check['checkId'], [])


def test_explicit_output_fields_bind_each_check_to_its_own_obligation_without_verdicts():
    comparison = presentation(); comparison['checkOutputShapeVersion'] = 1
    requirements = [
        {'obligationId':'first','checks':[
            {'checkId':'criterion:C1','processRequired':True},
            {'checkId':'criterion:C2','responseType':'limitation'},
            {'checkId':'criterion:C3','processRequired':True,'responseType':'limitation'}]},
        {'obligationId':'second','checks':[{'checkId':'criterion:C1','responseType':'explanation'}]}]
    before = deepcopy((comparison,requirements,CLAIMS))
    data = decode(renderer(QUESTION,requirements,CLAIMS,{},comparison,
                           process_explanations=True,literal_limits=True,coherence=True,
                           object_envelope=True)([]))
    shapes = data['checkOutputShapes']
    base = ['checkId','status','bindings','reason']
    assert shapes == [
        {'obligationId':'first','checks':[
            {'checkId':'criterion:C1','fields':base+['processLinks']},
            {'checkId':'criterion:C2','fields':base+['limitSpans']},
            {'checkId':'criterion:C3','fields':base+['processLinks','limitSpans']}]},
        {'obligationId':'second','checks':[{'checkId':'criterion:C1','fields':base}]}]
    assert data['requirements'] == requirements and data['claims'] == CLAIMS
    assert (comparison,requirements,CLAIMS) == before
    assert all(set(check)=={'checkId','fields'} for row in shapes for check in row['checks'])
    comparison.pop('checkOutputShapeVersion')
    assert 'checkOutputShapes' not in decode(renderer(QUESTION,requirements,CLAIMS,{},comparison)([]))


@pytest.mark.parametrize('mutation',[None,'foreign','metadata','drop','extra','waive','partial','incoherent','limit'])
def test_explicit_shapes_preserve_all_existing_acceptance_and_negative_checks(mutation):
    result,sent = audit(mutation,wire_mode='object_v1',explicit_shapes=True)
    assert len(sent)==1 and sent[0]['checkOutputShapes']
    assert (result['status']=='checked' and not result['gaps']) == (mutation is None)


@pytest.mark.parametrize('mutation',[None,'overlap','invented_operation'])
def test_compact_process_audit_retains_literal_operation_and_disjoint_roles(mutation):
    q='如何把输入视图转换为深度图？'
    plan=[{'obligations':[{'obligationId':'o','question':q}]}]
    claims=[{'claimId':'c','kind':'reported','text':'计算法线和距离并转换为深度图。','conditions':{}}]
    meta=presentation();meta['layout'][0]['claimIds']=['c']
    def invoke(rid,node,prompt,options,**kwargs):
        data=decode(prompt);rows=[]
        for goal in data['requirements']:
            checks=[]
            for required in goal['checks']:
                assert required['processRequired']
                checks.append({'checkId':required['checkId'],'status':'covered',
                    'bindings':[{'claimId':'c','field':'text'}],'reason':'Fixture connected operation.',
                    'processLinks':[{'input':{'request':q if mutation=='overlap' else '输入视图'},
                       'operation':{'id':'c','field':'text','excerpt':'not in answer' if mutation=='invented_operation' else '计算法线和距离并转换为深度图'},
                       'output':{'request':q if mutation=='overlap' else '深度图'}}]})
            rows.append({'obligationId':goal['obligationId'],'checks':checks})
        return {'content':json.dumps(rows)}
    result=audit_final_answer('r',q,plan,claims,[],invoke,json.loads,request_contract=5,
        diagnostics=True,shared_evidence_context=True,shared_decision_inputs=True,
        consolidated_instructions=True,comparison_cells=meta)
    assert (result['status']=='checked' and not result['gaps']) is (mutation is None)
