from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.experiment_generation_envelope import enabled,draft_prompt,refit
from services.deep_research.experiment_outline_encoding import encode,validate
from services.deep_research.experiment_planning import prepare_draft,prepare_plan
from services.deep_research.experiment_plan_encoding import wire_text
from test_deep_research_outline_encoding import record,prompt
from test_deep_research_plan_encoding import store_for,prepare,padded_basis
from test_deep_research_experiment_planning import response
from test_deep_research_lean_planning import lean_basis


def current():
    r=record();r.update(experimentOutlineEncodingContractVersion=2,experimentGenerationEnvelopeContractVersion=1)
    return r


def example():
    rows=[{'evidenceId':'E1','quote':'Exact operation α=0.1'},
        {'evidenceId':'E2','quote':'Exact dataset/member'},
        {'evidenceId':'E3','quote':'Optional passage. '+'x'*900}]
    plan={'basis':padded_basis(2859)}
    required=[{'evidenceIds':['E1','E2']}]
    return rows,plan,required


def renderer_for(r,rows,plan):
    packed=lambda values:json.dumps(values,ensure_ascii=False,separators=(',',':'))
    def render(values,padding=0):
        return prompt(prefix='h'*padding+'\nEvidence:\n'+packed(values)+'\n',suffix='\nActual complete plan:\n'+wire_text(plan['basis']))
    padding=24000-len(encode(r,render(rows[:2]))[0].encode())
    assert padding>0
    return lambda values:render(values,padding)


def test_actual_long_plan_reallocation_removes_only_unused_optional_evidence():
    r=current();rows,plan,bundles=example();before=deepcopy((rows,plan,bundles))
    render=renderer_for(r,rows,plan)
    raw,selected,audit=refit(r,rows,render,bundles,plan)
    assert selected==rows[:2] and audit['suppliedEvidenceAliases']==['E1','E2']
    assert audit['planningEvidenceAliases']==['E1','E2','E3']
    assert audit['unverifiedPlanReferences']==['E1'] and not audit['missingPremiseBundles']
    assert audit['encodedInputBytes']==24000 and wire_text(plan['basis']) in raw
    assert audit['planReferencesAreEvidenceApproval'] is False and (rows,plan,bundles)==before
    assert refit(r,rows,render,bundles,plan)==(raw,selected,audit)


def test_every_plan_reference_is_retained_even_if_the_complete_request_must_be_refused():
    r=current();rows,plan,bundles=example();render=renderer_for(r,rows,plan)
    plan['basis']['sourceRefs'].append('E3')
    raw,selected,audit=refit(r,rows,render,bundles,plan)
    assert selected==rows and audit['missingPremiseBundles'] and audit['encodedInputBytes']>24000
    store=store_for(2);store.value.update(r)
    saved=prepare_plan(store.value,prompt='Exact scientific input',aliases={'E1':'source1','E2':'source2','E3':'source3'},
        invoke=Mock(return_value=response(plan['basis'])),parse=json.loads,checkpoint=store.checkpoint)
    encoded,outline_audit=encode(r,raw)
    with pytest.raises(DeepResearchError) as exc:
        prepare_draft(store.value,saved,prompt=encoded,checkpoint=store.checkpoint,outline_encoding_audit=outline_audit)
    assert exc.value.code=='experiment_drafting_input_capacity'
    assert store.value['state']['experimentPlanning']['draftStatus']=='not_started_capacity'
    assert store.value['state']['experimentPlanning']['basis']==plan['basis']


@pytest.mark.parametrize('change',['foreign_plan_ref','foreign_bundle_ref','duplicate_row'])
def test_reallocation_never_acquires_new_sources_or_resolves_duplicate_identity_by_order(change):
    r=current();rows,plan,bundles=example()
    if change=='foreign_plan_ref':plan['basis']['sourceRefs'].append('E99')
    elif change=='foreign_bundle_ref':bundles.append({'evidenceIds':['E99']})
    else:rows.append(deepcopy(rows[0]))
    before=deepcopy((rows,plan,bundles))
    with pytest.raises(DeepResearchError,match='原文'):
        refit(r,rows,lambda values:prompt(),bundles,plan)
    assert (rows,plan,bundles)==before


def test_required_operation_context_is_preserved_whole_under_actual_plan_sizing():
    r=current();rows,plan,bundles=example();context={'before':'Exact original subject.','after':'Exact original condition.'}
    raw,selected,audit=refit(r,rows,lambda values:prompt(prefix=json.dumps(values,ensure_ascii=False)),bundles,plan,
        required_contexts={'E1':context})
    first=next(row for row in selected if row['evidenceId']=='E1')
    assert first['quote']==rows[0]['quote'] and first['sourceContext']==context and first['sourceContextRequired']
    assert not audit['missingPremiseBundles']


@pytest.mark.parametrize('version',[None,True,False,0,'1',2])
def test_envelope_requires_its_own_exact_server_contract(version):
    r=current();r['experimentGenerationEnvelopeContractVersion']=version
    assert not enabled(r)
    with pytest.raises(DeepResearchError,match='契约'):refit(r,[],lambda _:prompt(),[],{'basis':lean_basis()})


def test_thin_framing_retains_all_frozen_inputs_and_output_contract_fields():
    args=dict(question='完整原问题：α=0.1，不改写。',limit=300,clarification='Only the selected scene.',
        gaps=['未取得作者设置'],obligations=[{'obligationId':'o','question':'Exact frozen question','requiredSources':['work:v4']}],
        sources={'P1':{'workId':'work:v4','title':'Exact paper title'}},evidence_marker='EXACT_EVIDENCE_SLOT',
        claim_fields='claimId,text,kind,evidenceRefs,conditions,designRole,executionSpec',claim_limit=9,
        section_templates=['假设','方案','限制'])
    before=deepcopy(args);text=draft_prompt(**args)
    for key in ('question','clarification','evidence_marker','claim_fields'):assert args[key] in text
    for key in ('gaps','obligations','sources','section_templates'):
        assert json.dumps(args[key],ensure_ascii=False,separators=(',',':')) in text
    assert '300' in text and 'Maximum 9' in text and 'EVERY required role' in text
    assert 'reported/inference' in text and 'OWN supplied E' in text and 'tableBindings' in text
    assert args==before


def test_unknown_earlier_plan_cannot_opt_into_the_new_generation_envelope():
    store=store_for(2);r=current();r.pop('experimentGenerationEnvelopeContractVersion');store.value.update(r)
    invoke=Mock(side_effect=OSError('unknown'))
    with pytest.raises(OSError):prepare(store,invoke)
    frozen=deepcopy(store.value['state']['experimentPlanning']);store.value['experimentGenerationEnvelopeContractVersion']=1
    invoke.reset_mock()
    with pytest.raises(DeepResearchError,match='原输入'):prepare(store,invoke)
    invoke.assert_not_called();assert store.value['state']['experimentPlanning']==frozen


def test_graph_persists_actual_plan_allocation_and_exact_frozen_body():
    from services.deep_research.graph import make_synthesize_node
    from test_deep_research_experiment_planning import Store
    from test_deep_research_experiment_representation import wrapped_claims
    r=current();store=Store(r)
    invoke=Mock(side_effect=[response(lean_basis()),response({'sections':[],'claims':wrapped_claims()})])
    result=make_synthesize_node(invoke,store.update)({'run_id':'r'})
    assert not result.get('error_code') and invoke.call_count==2
    actual=store.value['state']['generationPremiseAllocation'];saved=store.value['state']['experimentPlanning']
    assert not actual['missingPremiseBundles'] and not actual['planReferencesAreEvidenceApproval']
    assert set(actual['requiredEvidenceAliases'])<=set(actual['suppliedEvidenceAliases'])
    assert set(actual['suppliedEvidenceIds'])<=set(actual['planningEvidenceIds'])
    validate(store.value,saved['draftRequest']['prompt'],saved['outlineEncodingAudit'])
    assert actual['encodedInputBytes']==len(saved['draftRequest']['prompt'].encode())<=24000


@pytest.mark.parametrize('replacement',[None,True,'1',0,2])
def test_generation_envelope_is_server_owned_and_immutable(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'runs.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        value,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Propose an experiment',
            'experimentGenerationEnvelopeContractVersion':replacement,'deferStart':True},start_async=False)
        assert value['experimentGenerationEnvelopeContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(value['runId'],lambda r:{**r,'experimentGenerationEnvelopeContractVersion':replacement})
    finally:facade.shutdown()
