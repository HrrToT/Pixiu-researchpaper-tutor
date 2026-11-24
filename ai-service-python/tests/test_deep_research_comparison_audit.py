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
          comparison=None, claims=CLAIMS, require_joint=False, compact_instructions=False):
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
                    check['limitSpans'] = [{'claimId':'b','field':'text','excerpt':CLAIMS[1]['text']}]
        check = rows[0]['checks'][0]
        if mutation == 'foreign':check['bindings'] = [{'claimId':'foreign','field':'text'}]
        elif mutation == 'metadata':check['bindings'] = [{'claimId':'a','field':'table'}]
        elif mutation == 'drop':rows[0]['checks'].pop()
        elif mutation == 'extra':check['unrequested'] = True
        elif mutation == 'partial':check.update(status='partial',reason='The answer is only partial.')
        elif mutation == 'limit':rows[0]['checks'][1]['limitSpans'][0]['excerpt'] = 'not in answer'
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
        rows.append({'auditType':'answer_coherence','coherent':mutation != 'incoherent',
            'issues':[] if mutation != 'incoherent' else [{'kind':'contradiction',
              'bindings':[{'claimId':'a','field':'text'}], 'reason':'Fixture joint contradiction.'}]})
        if wire_mode is not None:
            from services.deep_research.structured_output import normalize
            if wire_mode=='object_v1':
                if compact_instructions:
                    assert '"items":ROWS,"auditType":"answer_coherence"' in prompt
                else:
                    assert 'Root coherence fields (never items)' in prompt
                reply = {'content':json.dumps({'items':rows[:-1],**rows[-1]})}
                if mutation == 'truncated':
                    reply['finishReason'] = 'length'
                return normalize(node,reply,comparison_audit_envelope=True)
            assert 'Return ONLY {"items":[ROWS]}' in prompt and 'INSIDE items (NEVER at root)' in prompt
            data={'items':rows} if wire_mode=='valid' else {'items':rows[:-1],**rows[-1]}
            return normalize(node,{'content':json.dumps(data)})
        return {'content':json.dumps(rows)}
    before = deepcopy((PLAN, claims, evidence))
    comparison = presentation() if comparison is None else deepcopy(comparison)
    if explicit_shapes:
        comparison['checkOutputShapeVersion'] = 1
    result = audit_final_answer('r',QUESTION,PLAN,claims,evidence,invoke,json.loads,
        request_contract=5, diagnostics=True,literal_dimensions=True, coherence=True,
        task_sources=True,request_semantics=2,binding_catalog=True,scoped_catalog=True,
        shared_decision_inputs=True,shared_evidence_context=True,consolidated_instructions=True,
        literal_limits=True,comparison_cells=comparison,compact_comparison_layout=compact_layout,
        compact_comparison_checks=compact_checks,budget=budget,
        fit_compact_comparison_budget=fit_compact_budget,
        require_joint_conclusions=require_joint,
        compact_comparison_instructions=compact_instructions,
        **({'comparison_audit_envelope':True} if wire_mode=='object_v1' else {}))
    assert before == (PLAN, claims, evidence)
    return result, sent


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
