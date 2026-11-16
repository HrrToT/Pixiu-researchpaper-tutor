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


def audit(mutation=None, evidence=None, wire_mode=None):
    evidence = deepcopy(EVIDENCE if evidence is None else evidence)
    sent = []
    def invoke(rid, node, prompt, options, **kwargs):
        assert node == 'verify_answer_coverage' and kwargs == {'use_reserve':True}
        data = decode(prompt); sent.append(data)
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
        rows.append({'auditType':'answer_coherence','coherent':mutation != 'incoherent',
            'issues':[] if mutation != 'incoherent' else [{'kind':'contradiction',
              'bindings':[{'claimId':'a','field':'text'}], 'reason':'Fixture joint contradiction.'}]})
        if wire_mode is not None:
            from services.deep_research.structured_output import normalize
            assert 'Return ONLY {"items":[ROWS]}' in prompt and 'INSIDE items (NEVER at root)' in prompt
            data={'items':rows} if wire_mode=='valid' else {'items':rows[:-1],**rows[-1]}
            return normalize(node,{'content':json.dumps(data)})
        return {'content':json.dumps(rows)}
    before = deepcopy((PLAN, CLAIMS, evidence))
    result = audit_final_answer('r',QUESTION,PLAN,CLAIMS,evidence,invoke,json.loads,
        request_contract=5, diagnostics=True,literal_dimensions=True, coherence=True,
        task_sources=True,request_semantics=2,binding_catalog=True,scoped_catalog=True,
        shared_decision_inputs=True,shared_evidence_context=True,consolidated_instructions=True,
        literal_limits=True,comparison_cells=presentation())
    assert before == (PLAN, CLAIMS, evidence)
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


@pytest.mark.parametrize('mode',['valid','root_coherence'])
def test_actual_native_envelope_accepts_only_coherence_inside_items(mode):
    result,sent=audit(wire_mode=mode)
    assert len(sent)==1
    if mode=='valid':assert result['status']=='checked' and not result['gaps']
    else:assert result['status']=='invalid_response' and result['gaps']


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
