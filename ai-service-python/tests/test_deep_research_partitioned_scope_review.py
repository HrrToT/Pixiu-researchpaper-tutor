from copy import deepcopy
import json
import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.scope_expression import materialize
from services.deep_research.scope_expression_review import context_for_record
from services.deep_research.partitioned_scope_review import observation_claims
from services.deep_research.tools import BudgetedSemanticChecker


def inputs(settings=True, boundaries=True):
    expression={'observedSettings':[{'subject':'Method A','attribute':'evaluated setting','value':'66%'}] if settings else [],
                'notEstablished':['Method A preserves quality at every setting'] if boundaries else []}
    claim,audit=materialize({'claimId':'c','kind':'inference','text':'','conditions':{},
                            'evidenceRefs':['own'],'scopeExpression':expression})
    record={'scopeExpressionReviewContractVersion':2,'state':{'synthesisScopeExpressionAudit':[audit]}}
    evidence=[{'evidenceId':'own','quote':'Method A retained quality at 66%.',
               'sourceContext':'At 70% quality declined.'},
              {'evidenceId':'foreign','quote':'An unrelated universal theorem proves preservation.'}]
    return claim,expression,record,evidence


def boundary_row(proposition):
    return {'index':0,'proposition':proposition,'relation':'not_entailed',
            'quantification':'explicit','isNegation':False,'authorOmission':False,
            'reason':'A measured setting does not establish preservation at every setting.',
            'premises':[{'evidenceId':'E1','path':['quote']}]}


def checker_for(claim,expression,record,evidence,*,modify=None,fact_failure=False,flags=True):
    calls=[]
    def invoke(**kw):
        calls.append(kw)
        if 'Review evidence ENTAILMENT' in kw['prompt']:
            rows=[boundary_row(p) for p in expression['notEstablished']]
            if modify:modify(rows,kw)
            return {'content':json.dumps(rows),'finishReason':'stop'}
        atom=observation_claims(claim,expression)[len([c for c in calls if 'Review evidence ENTAILMENT' not in c['prompt']])-1]
        verdict={'claimId':atom['claimId'],'status':'failed' if fact_failure else 'passed',
                 'reason':'Fact unsupported' if fact_failure else 'Own source supports the setting.',
                 'scopeAudit':{'claimStrength':'bounded','evidenceStrength':'bounded',
                     'supported':True,'statementPath':['text'],'premises':[{'evidenceId':'E1','path':['quote']}]}}
        return {'content':json.dumps([verdict]),'finishReason':'stop'}
    checker=BudgetedSemanticChecker(invoke,'r',partitioned_scope_review=True,
        scope_expression_context=lambda targets:context_for_record(record,targets),
        factual_scope=flags,complete_factual_scope=flags,audit_source_fields=flags,audit_target_fields=flags,
        isolate_factual_claims=True)
    return checker,calls


def test_observation_facts_and_non_entailment_are_independent_and_preserve_sources():
    claim,expression,record,evidence=inputs();before=deepcopy((claim,expression,record,evidence))
    checker,calls=checker_for(claim,expression,record,evidence)
    result=checker([claim],evidence)[0]
    assert result['claimId']=='c' and result['status']=='passed' and len(calls)==2
    assert 'Scope-strength audit' in calls[0]['prompt']
    assert 'Review evidence ENTAILMENT' in calls[1]['prompt'] and 'Scope-strength audit' not in calls[1]['prompt']
    assert all('unrelated universal theorem' not in c['prompt'] for c in calls)
    assert all(c['use_reserve'] is True and c['node']=='verify' for c in calls)
    assert result['partitionedScopeAudit']['notEstablished'][0]['premises'][0]['evidenceId']=='own'
    assert (claim,expression,record,evidence)==before


def test_failed_fact_is_never_upgraded_by_an_epistemic_operator():
    claim,expression,record,evidence=inputs();checker,calls=checker_for(claim,expression,record,evidence,fact_failure=True)
    result=checker([claim],evidence)[0]
    assert result['status']=='failed' and 'Fact unsupported' in result['reason'] and len(calls)==1


@pytest.mark.parametrize('mutation',['entailed','undetermined','ambiguous','negation','omission',
                                   'foreign','spliced','wrong_proposition','bool_index','empty_reason'])
def test_boundary_needs_exact_proposition_explicit_quantification_and_own_bindings(mutation):
    claim,expression,record,evidence=inputs()
    def change(rows,_):
        row=rows[0]
        if mutation in ('entailed','undetermined'):row['relation']=mutation
        elif mutation=='ambiguous':row['quantification']='ambiguous'
        elif mutation=='negation':row['isNegation']=True
        elif mutation=='omission':row['authorOmission']=True
        elif mutation=='foreign':row['premises']=[{'evidenceId':'foreign','path':['quote']}]
        elif mutation=='spliced':row['premises']=[{'evidenceId':'E1','quote':'Method A at 66%.'}]
        elif mutation=='wrong_proposition':row['proposition']='A weaker proposition'
        elif mutation=='bool_index':row['index']=False
        else:row['reason']=''
    checker,calls=checker_for(claim,expression,record,evidence,modify=change)
    assert checker([claim],evidence)[0]['status']=='failed' and len(calls)==2


@pytest.mark.parametrize('settings,boundaries',[(True,False),(False,True)])
def test_single_operator_forms_review_every_present_part(settings,boundaries):
    claim,expression,record,evidence=inputs(settings,boundaries)
    checker,calls=checker_for(claim,expression,record,evidence)
    assert checker([claim],evidence)[0]['status']=='passed' and len(calls)==1


@pytest.mark.parametrize('kind',['truncated','missing','extra_field','budget','unknown'])
def test_invalid_or_unresolved_boundary_does_not_become_evidence_insufficiency(kind):
    claim,expression,record,evidence=inputs(settings=False);calls=[]
    def invoke(**kw):
        calls.append(kw)
        if kind in ('budget','unknown'):raise DeepResearchError(kind,'Do not resend')
        rows=[boundary_row(expression['notEstablished'][0])]
        if kind=='missing':rows=[]
        if kind=='extra_field':rows[0]['status']='failed'
        return {'content':json.dumps(rows),'finishReason':'length' if kind=='truncated' else 'stop'}
    checker=BudgetedSemanticChecker(invoke,'r',partitioned_scope_review=True,
        scope_expression_context=lambda targets:context_for_record(record,targets))
    with pytest.raises(DeepResearchError,match='Do not resend|未完整返回'):
        checker([claim],evidence)
    assert len(calls)==1


def test_revision_uses_same_partition_and_does_not_inherit_other_claim_evidence():
    claim,expression,record,evidence=inputs();checker,calls=checker_for(claim,expression,record,evidence)
    result=checker.check_revisions([claim],evidence,[{'claimId':'other','kind':'reported',
                                                    'text':'Other fact','evidenceRefs':['foreign']}])
    assert result[0]['status']=='passed' and all(c['node']=='verify_repair' for c in calls)
    assert all('unrelated universal theorem' not in c['prompt'] for c in calls)


def test_synthetic_ids_are_deterministic_and_not_parent_verdict_ids():
    claim,expression,record,evidence=inputs();atoms=observation_claims(claim,expression)
    assert atoms==observation_claims(claim,expression)
    assert atoms[0]['claimId']!=claim['claimId'] and atoms[0]['evidenceRefs']==claim['evidenceRefs']
    assert context_for_record(record,atoms)=={}


def test_complete_own_evidence_over_capacity_is_not_truncated_or_sent():
    claim,expression,record,evidence=inputs(settings=False)
    evidence[0]['quote']='Original source text. '*2000
    checker,calls=checker_for(claim,expression,record,evidence)
    with pytest.raises(DeepResearchError,match='超过输入容量'):
        checker([claim],evidence)
    assert calls==[]


def test_missing_own_source_fails_without_substituting_foreign_evidence():
    claim,expression,record,evidence=inputs(settings=False)
    checker,calls=checker_for(claim,expression,record,evidence)
    assert checker([claim],evidence[1:])[0]['status']=='failed' and calls==[]


def test_new_policy_does_not_partition_a_mismatched_saved_expression():
    claim,expression,record,evidence=inputs(settings=False)
    record['state']['synthesisScopeExpressionAudit'][0]['renderedText']='Different original statement'
    calls=[]
    def invoke(**kw):
        calls.append(kw)
        return {'content':json.dumps([{'claimId':'c','status':'failed','reason':'Ordinary factual check'}])}
    checker=BudgetedSemanticChecker(invoke,'r',partitioned_scope_review=True,
        scope_expression_context=lambda targets:context_for_record(record,targets))
    result=checker([claim],evidence)
    assert result[0]['status']=='failed' and result[0]['reason']=='Ordinary factual check'
    assert len(calls)==1 and 'Review evidence ENTAILMENT' not in calls[0]['prompt']


def test_ordinary_finding_gets_review_budget_before_additional_scope_operations():
    claim,expression,record,evidence=inputs();calls=[]
    plain={'claimId':'finding','kind':'reported','text':'Method A retained quality.',
           'conditions':{},'evidenceRefs':['own']}
    def invoke(**kw):
        calls.append(kw)
        if 'Review evidence ENTAILMENT' in kw['prompt']:
            rows=[boundary_row(expression['notEstablished'][0])]
        else:
            targets=json.loads(kw['prompt'].split('Claims:\n',1)[1].split('\n\nEvidence:',1)[0])
            rows=[{'claimId':c['claimId'],'status':'passed'} for c in targets]
        return {'content':json.dumps(rows),'finishReason':'stop'}
    checker=BudgetedSemanticChecker(invoke,'r',partitioned_scope_review=True,isolate_factual_claims=True,
        scope_expression_context=lambda targets:context_for_record(record,targets))
    verdicts=checker([plain,claim],evidence)
    assert [(v['claimId'],v['status']) for v in verdicts]==[('finding','passed'),('c','passed')]
    assert '"claimId":"finding"' in calls[0]['prompt']
    assert len(calls)==3 and 'Review evidence ENTAILMENT' in calls[-1]['prompt']


def test_entailment_keeps_own_table_mapping_conditions_and_publication_identity():
    claim,expression,record,evidence=inputs(settings=False)
    fields={'tableData':{'groups':[['Dataset A',['SSIM']]],'rows':[[1,'Method A',['0.9']]]},
            'conditions':{'dataset':'Dataset A'},'sourcePublicationIdentity':{'title':'Actual paper'}}
    evidence[0].update(deepcopy(fields));before=deepcopy(evidence)
    checker,calls=checker_for(claim,expression,record,evidence)
    assert checker([claim],evidence)[0]['status']=='passed'
    visible=json.loads(calls[0]['prompt'].split('\nEvidence:\n')[1])
    assert len(visible)==1 and all(visible[0][key]==value for key,value in fields.items())
    assert evidence==before
