from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.experiment_representation import normalize_claims, normalize_spec, GUIDANCE
from services.deep_research.group_spec import validate_group_spec
from services.deep_research.experiment_protocol import protocol_errors
from services.deep_research.experiment_workflow import workflow_errors
from services.deep_research.budget_spec import validate_budget_spec
from services.deep_research.repair import _prepare_repair, _parse_repair_response, repair_rejected
from services.deep_research.contracts import DeepResearchError
from services.deep_research.verification import verify_claims
from services.deep_research.execution_materialization import normalize_execution_spec
from services.deep_research.graph import make_synthesize_node
from test_deep_research_shared_experiment_repair import inputs
from test_deep_research_lean_planning import record, lean_basis
from test_deep_research_experiment_planning import Store, response


def wrapped_claims():
    claims = inputs()[0]['claims']
    for claim in claims:
        if 'executionSpec' in claim:
            claim['executionSpec'] = {claim['designRole']: claim['executionSpec']}
    return claims


def prepare(**kw):
    report, checks, evidence = inputs()
    return _prepare_repair(report, checks, evidence, 'Propose a whole-stage experiment.',
        experimental_intent=3, shared_experiment_schema=True, experimental_edits=True,
        experimental_diagnostics=True, experimental_nested_tables=True, **kw)


def test_exact_role_wrappers_preserve_every_inner_value_and_all_nonconfig_fields():
    original = wrapped_claims(); before = deepcopy(original)
    normalized, audit = normalize_claims(original)
    for old, new in zip(original, normalized):
        assert {k:v for k,v in new.items() if k!='executionSpec'} == {k:v for k,v in old.items() if k!='executionSpec'}
        if 'executionSpec' in old:
            assert new['executionSpec'] == old['executionSpec'][old['designRole']]
    assert {a['claimId'] for a in audit} == {c['claimId'] for c in original if 'executionSpec' in c}
    assert all(a['kind']=='single_role_wrapper' for a in audit)
    assert original == before


@pytest.mark.parametrize('variant', ['extra_outer', 'extra_inner', 'missing_inner', 'double_wrapper',
    'wrong_role', 'factual', 'unversioned', 'bool_version', 'bad_kind'])
def test_ambiguous_incomplete_or_nonexperimental_objects_are_not_reinterpreted(variant):
    claim = next(c for c in wrapped_claims() if c['designRole']=='groups')
    if variant=='extra_outer': claim['executionSpec']['notes']='Keep this unknown choice.'
    elif variant=='extra_inner': claim['executionSpec']['groups']['notes']='Keep this unknown choice.'
    elif variant=='missing_inner': claim['executionSpec']['groups'].pop('factors')
    elif variant=='double_wrapper': claim['executionSpec']={'groups':claim['executionSpec']}
    elif variant=='wrong_role': claim['executionSpec']={'budget':claim['executionSpec']['groups']}
    elif variant=='factual': claim['kind']='reported'
    elif variant=='unversioned': claim.pop('designContractVersion')
    elif variant=='bool_version': claim['designContractVersion']=True
    elif variant=='bad_kind': claim['kind']=['proposal']
    before=deepcopy(claim); result,audit=normalize_claims([claim])
    assert result==[before] and not audit and claim==before


@pytest.mark.parametrize('form', ['rows', 'table'])
def test_declared_operation_parameter_columns_restore_exact_values_without_rounding(form):
    claim = next(c for c in inputs()[0]['claims'] if c['designRole']=='groups')
    operation=claim['executionSpec']['factors'][0]['treatment']
    operation['parameters'] = ([['threshold','number',1e-8],['policy','choice','training_only']]
        if form=='rows' else {'@':[['value','name','type'],[[1e-8,'threshold','number'],['training_only','policy','choice']]]})
    before=deepcopy(claim); [result],audit=normalize_claims([claim])
    assert result['executionSpec']['factors'][0]['treatment']['parameters']==[
        {'name':'threshold','type':'number','value':1e-8},{'name':'policy','type':'choice','value':'training_only'}]
    assert not validate_group_spec(result['executionSpec']) and claim==before
    assert audit[0]['path']=='/executionSpec/factors/0/treatment/parameters' and audit[0]['rows']==2


@pytest.mark.parametrize('parameters', [
    [['rate','number',True]], [['rate','number',float('inf')]], [['rate','number','0.1']],
    [['mode','choice',3]], [['a','number',1],['a','number',2]], [['name','number']],
    [['rate','number',1],{'name':'mode','type':'choice','value':'mixed'}],
    {'@':[['name','type','value'],[['a','number']]]}, {'@':[['name','type','type'],[['a','number',1]]]},
    {'@':[['name','type','value'],[['a','number',1]]],'other':'retain'},
])
def test_invalid_or_mixed_parameter_collections_are_not_partially_fixed(parameters):
    claim = next(c for c in inputs()[0]['claims'] if c['designRole']=='groups')
    claim['executionSpec']['factors'][0]['treatment']['parameters']=parameters
    before=deepcopy(claim);result,audit=normalize_claims([claim])
    assert result==[before] and not audit and claim==before


def test_literal_state_values_conditions_and_unrecognized_operation_fields_stay_untouched():
    claim = next(c for c in inputs()[0]['claims'] if c['designRole']=='steps')
    literal={'action':'literal data, not operation','parameters':[['x','number',1]]}
    claim['conditions']=deepcopy(literal)
    claim['executionSpec']['baselineInitialization']['stateDefinitions'][0]['initializer']={'mode':'constant','value':deepcopy(literal)}
    claim['executionSpec']['baselineInitialization']['creation']={**deepcopy(literal),'extra':'do not discard'}
    before=deepcopy(claim);result,audit=normalize_claims([claim])
    assert result==[before] and not audit


def test_inner_science_and_budget_failures_are_preserved_after_wrapper_removal():
    claims=wrapped_claims(); by_role={c['designRole']:c for c in claims}
    by_role['budget']['executionSpec']['budget']['recovery']['groups']['0']=0
    by_role['steps']['executionSpec']['steps']['baselineInitialization']['stateDefinitions'][0]['shape']=[0,3]
    result,audit=normalize_claims(claims); roles={c['designRole']:c for c in result}
    assert audit and validate_budget_spec(roles['budget']['executionSpec'])
    assert 'workflow.states.shape' in workflow_errors(roles['steps']['executionSpec'],4)
    assert not verify_claims([roles['groups']],inputs()[2],lambda *_:[])['accepted']


@pytest.mark.parametrize('version', [5,6])
def test_generation_gate_keeps_raw_model_response_and_audits_only_new_contract(version):
    current=record();current['experimentDraftContractVersion']=version;store=Store(current)
    body={'sections':[],'claims':wrapped_claims()}; original=deepcopy(body)
    invoke=Mock(side_effect=[response(lean_basis()),response(body)])
    result=make_synthesize_node(invoke,store.update)({'run_id':'r'})
    assert 'error_code' not in result and invoke.call_count==2 and body==original
    assert (GUIDANCE in invoke.call_args.args[2]) is (version==6)
    saved=store.value['state']; claims=saved['reportBody']['claims']
    assert bool(saved.get('experimentRepresentationAudit')) is (version==6)
    for claim in claims:
        raw=next(c for c in original['claims'] if c['claimId']==claim['claimId'])
        expected=(raw.get('executionSpec',{}).get(raw['designRole']) if version==6
            else normalize_execution_spec(raw['designRole'],raw.get('executionSpec')))
        assert claim.get('executionSpec')==expected
        assert not claim.get('verification')
    assert saved['evidence']==current['state']['evidence']


def test_new_repair_expands_parameter_rows_then_uses_original_source_and_structural_checks():
    old=prepare(); new=prepare(experimental_representation=True)
    patch=[{'claimId':'groups','edits':[{'op':'replace','path':'/executionSpec/factors/0/treatment/parameters',
        'value':[['threshold','number',0.01]]}]}]
    encoded={'content':json.dumps(patch)};audit=[]
    legacy=_parse_repair_response(old,encoded,json.loads,strict_response=True)
    revised=_parse_repair_response(new,encoded,json.loads,strict_response=True,representation_audit=audit)
    assert validate_group_spec(legacy[0]['executionSpec'])
    assert not validate_group_spec(revised[0]['executionSpec']) and audit[0]['kind']=='operation_parameter_rows'
    assert revised[0]['evidenceRefs']==new['originals']['groups']['evidenceRefs']
    patch[0]['edits'].append({'op':'replace','path':'/evidenceRefs','value':['foreign']})
    assert _parse_repair_response(new,{'content':json.dumps(patch)},json.loads,strict_response=True)==[]


def test_pending_new_request_is_frozen_and_legacy_resume_cannot_opt_into_normalization():
    report,checks,evidence=inputs();saved=[]
    args=dict(experimental_intent=3,shared_experiment_schema=True,experimental_edits=True,
        experimental_diagnostics=True,experimental_nested_tables=True,experimental_representation=True)
    invoke=Mock(side_effect=OSError('unknown'))
    with pytest.raises(OSError):
        repair_rejected(report,checks,evidence,'Q',Mock(),json.loads,**args,invoke_request=invoke,
            checkpoint=lambda s:saved.append(deepcopy(s)))
    assert saved[-1]['pending']['request']['prepared']['representationContractVersion']==1
    frozen=deepcopy(saved[-1]);invoke.reset_mock();args.pop('experimental_representation')
    with pytest.raises(DeepResearchError,match='原始输入'):
        repair_rejected(report,checks,evidence,'Q',Mock(),json.loads,**args,batch_state=frozen,invoke_request=invoke)
    invoke.assert_not_called();assert saved[-1]==frozen


def test_completed_normalization_audit_is_checkpointed_without_promoting_revisions():
    report,checks,evidence=inputs();saved=[]
    patch=[{'claimId':'groups','edits':[{'op':'replace','path':'/executionSpec/factors/0/treatment/parameters',
        'value':[['threshold','number',0.01]]}]}]
    result=repair_rejected(report,checks,evidence,'Q',Mock(),json.loads,experimental_intent=3,
        shared_experiment_schema=True,experimental_edits=True,experimental_diagnostics=True,
        experimental_nested_tables=True,experimental_representation=True,
        invoke_request=Mock(return_value={'content':json.dumps(patch)}),checkpoint=lambda s:saved.append(deepcopy(s)))
    assert len(result)==1 and not result[0].get('verification')
    assert saved[-1]['representationNormalizationAudit']['0'][0]['kind']=='operation_parameter_rows'
    assert 'pending' not in saved[-1]
