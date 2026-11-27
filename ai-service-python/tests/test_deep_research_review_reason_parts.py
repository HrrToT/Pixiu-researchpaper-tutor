from copy import deepcopy
import json
import pytest
from services.deep_research.contracts import DeepResearchError
from services.deep_research.review_reason_parts import expand,GUIDANCE
from services.deep_research.factual_decision import decode
from test_deep_research_factual_decision import checker,response,target,evidence


def row(supported=True):
    result=response(supported);result.pop('reason')
    result['reasonParts']=[{'text':'The source reports setting 12.','evidenceId':'E1','path':['quote'],'excerpt':'setting 12'},
                           {'text':'The asserted relationship is supported.' if supported else 'The asserted relationship is unresolved.'}]
    return result


def opts():return dict(review_diagnostic_bindings=True,integrated_diagnostic_schema=True,review_reason_parts=True)


@pytest.mark.parametrize('supported',[True,False])
def test_exact_parts_preserve_all_text_all_source_bindings_and_actual_decision(supported):
    raw=row(supported);before=deepcopy(raw);parts=raw['reasonParts'];result=decode([raw],diagnostic_facts=True,reason_parts=True)[0]
    assert result['reason']=='\n'.join(p['text'] for p in parts)
    assert result['diagnosticFacts']==[{'statement':parts[0]['text'],**{k:parts[0][k] for k in ('evidenceId','path','excerpt')}}]
    assert result['scopeAudit']==raw['scopeAudit'] and result['status']==('passed' if supported else 'failed') and raw==before


def test_seventeen_segments_preserve_the_complete_review_without_bypassing_new_fact_checks():
    raw = row()
    raw['reasonParts'] += [{'text': 'The cited clause is addressed.'} for _ in range(15)]
    result = checker(lambda **_: {'content': json.dumps([raw])}, **opts())([target()], evidence())[0]
    assert result['status'] == 'passed' and result['reviewDiagnosticAudit']['bindingCount'] == 1
    raw['reasonParts'][-1] = {'text': 'The replacement coefficient is 0.9.'}
    result = checker(lambda **_: {'content': json.dumps([raw])}, **opts())([target()], evidence())[0]
    assert result['executionState'] == 'received_invalid'
    assert result['reviewDiagnosticAudit']['unboundNewNumberCount'] == 1


@pytest.mark.parametrize('supported',[True,False])
def test_real_checker_uses_new_wire_then_original_diagnostic_and_scope_gates(supported):
    sent=[];raw=row(supported)
    def invoke(**kw):sent.append(kw);return {'content':json.dumps([raw]),'finishReason':'stop'}
    result=checker(invoke,**opts())([target()],evidence())[0]
    assert result['status']==('passed' if supported else 'failed') and result['reviewDiagnosticAudit']['errors']==[]
    assert len(sent)==1 and GUIDANCE in sent[0]['prompt'] and 'with claimId, reasonParts, and scopeAudit.' in sent[0]['prompt']
    assert 'source fact is added to reason' not in sent[0]['prompt']


@pytest.mark.parametrize('bad',['foreign','hidden_path','invented_quote','new_number','wrong_number'])
def test_new_encoding_never_bypasses_own_source_fields_literal_excerpts_or_new_numbers(bad):
    raw=row();part=raw['reasonParts'][0]
    if bad=='foreign':part['evidenceId']='foreign'
    elif bad=='hidden_path':part['path']=['sourceTitle']
    elif bad=='invented_quote':part['excerpt']='invented source sentence'
    elif bad=='new_number':raw['reasonParts'].append({'text':'The replacement coefficient is 0.9.'})
    else:part['text']='The actual setting is 24.'
    result=checker(lambda **_: {'content':json.dumps([raw])},**opts())([target()],evidence())[0]
    assert result['status']=='failed' and result['executionState']=='received_invalid' and result['reviewDiagnosticAudit']['errors']


@pytest.mark.parametrize('bad',['missing','empty','too_many','nonobject','blank','mixed_reason','mixed_facts','partial_binding','extra_field'])
def test_ambiguous_or_lossy_encodings_cannot_be_silently_repaired(bad):
    raw=row()
    if bad=='missing':raw.pop('reasonParts')
    elif bad=='empty':raw['reasonParts']=[]
    elif bad=='too_many':raw['reasonParts']*=13
    elif bad=='nonobject':raw['reasonParts'][0]='text'
    elif bad=='blank':raw['reasonParts'][0]['text']=' '
    elif bad=='mixed_reason':raw['reason']='conflicting explanation'
    elif bad=='mixed_facts':raw['diagnosticFacts']=[]
    elif bad=='partial_binding':raw['reasonParts'][0].pop('excerpt')
    else:raw['reasonParts'][0]['approved']=True
    with pytest.raises(DeepResearchError):decode([raw],diagnostic_facts=True,reason_parts=True)


@pytest.mark.parametrize('bad',['unsupported','foreign_scope','universal','conflicting_decision'])
def test_canonical_diagnostic_does_not_approve_failed_scope_or_conflicting_decisions(bad):
    raw=row()
    if bad=='unsupported':raw['scopeAudit']['supported']=False
    elif bad=='foreign_scope':raw['scopeAudit']['premises'][0]['evidenceId']='foreign'
    elif bad=='universal':raw['scopeAudit']['claimStrength']='universal'
    else:
        raw['scopeAudit']['status']='passed'
        with pytest.raises(DeepResearchError):decode([raw],diagnostic_facts=True,reason_parts=True)
        return
    assert checker(lambda **_: {'content':json.dumps([raw])},**opts())([target()],evidence())[0]['status']=='failed'


def test_legacy_checker_messages_and_decisions_remain_exact_when_new_policy_is_off():
    raw={**response(),'diagnosticFacts':[]};sent=[]
    def invoke(**kw):sent.append(deepcopy(kw));return {'content':json.dumps([raw])}
    base=checker(invoke,review_diagnostic_bindings=True,integrated_diagnostic_schema=True)([target()],evidence());old=sent.pop()
    assert checker(invoke,review_diagnostic_bindings=True,integrated_diagnostic_schema=True,review_reason_parts=False)([target()],evidence())==base
    assert sent.pop()==old
    with pytest.raises(DeepResearchError):decode([row()],diagnostic_facts=True)


def test_singleton_native_transport_accepts_new_schema_only_with_frozen_flag_and_keeps_raw_parts():
    from services.deep_research.structured_output import normalize
    raw=row();response_packet={'content':json.dumps(raw),'finishReason':'stop'}
    new=normalize('verify',response_packet,factual_singleton=True,factual_diagnostics=True,factual_reason_parts=True)
    assert new['structuredOutput']['receivedShape']=='single_factual_candidate'
    assert json.loads(new['content'])==raw
    old=normalize('verify',response_packet,factual_singleton=True,factual_diagnostics=True)
    assert old['content']=='null'


@pytest.mark.parametrize('version', [1, 2, 3])
def test_new_reviewer_wording_leaves_the_numeric_validation_gate_intact(version):
    sent = []
    raw = row()
    raw['reasonParts'].append({'text': '论文给出了两个条件。'})

    def invoke(**kwargs):
        sent.append(kwargs['prompt'])
        return {'content':json.dumps([raw])}

    check = checker(invoke, **{**opts(), 'review_reason_parts':version})
    rejected = check([target()], evidence())[0]
    assert rejected['reviewDiagnosticAudit']['errors'] == ['new_diagnostic_numbers_not_bound']
    assert ('solely to summarize' in sent[-1]) is (version in (2, 3))
    raw['reasonParts'][-1]['text'] = 'The conditions agree with the cited text.'
    assert check([target()], evidence())[0]['status'] == 'passed'


@pytest.mark.parametrize('variant', ['supported', 'unsupported', 'missing_premises', 'foreign_premise', 'wrong_scope'])
def test_compact_supported_review_requires_its_own_valid_scope(variant):
    raw = row()
    raw['reasonParts'] = []
    scope = raw['scopeAudit']
    if variant == 'unsupported':
        scope['supported'] = False
    elif variant == 'missing_premises':
        scope['premises'] = []
    elif variant == 'foreign_premise':
        scope['premises'][0]['evidenceId'] = 'foreign'
    elif variant == 'wrong_scope':
        scope['claimStrength'] = 'universal'

    packet = {'content':json.dumps(raw),'finishReason':'stop'}
    from services.deep_research.structured_output import normalize
    policy = dict(factual_singleton=True, factual_diagnostics=True, factual_reason_parts=True)
    assert normalize('verify', packet, **policy)['content'] == 'null'
    normalized = normalize('verify', packet, **policy, factual_compact_supported=True)
    if variant in {'unsupported', 'missing_premises'}:
        assert normalized['content'] == 'null'
    else:
        assert json.loads(normalized['content']) == raw

    check = checker(lambda **_: {'content':json.dumps([raw])}, **{**opts(), 'review_reason_parts':3})
    if variant in {'unsupported', 'missing_premises'}:
        with pytest.raises(DeepResearchError, match='支持判定'):
            check([target()], evidence())
        return
    result = check([target()], evidence())[0]
    assert result['status'] == ('passed' if variant == 'supported' else 'failed')
    if variant == 'supported':
        assert result['diagnosticFacts'] == []
        assert result['reviewDiagnosticAudit']['errors'] == []


@pytest.mark.parametrize('replacement',[None,True,False,0,'1',1,3])
def test_factory_owns_immutable_parts_policy(tmp_path,replacement):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize();facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        created,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'核查','reviewReasonPartsContractVersion':replacement},start_async=False)
        saved=repo.require_run(created['runId']);assert type(saved['reviewReasonPartsContractVersion']) is int and saved['reviewReasonPartsContractVersion']==2
        with pytest.raises(ValueError,match='Immutable'):repo.update_run(saved['runId'],lambda r:{**r,'reviewReasonPartsContractVersion':replacement})
    finally:facade.shutdown()
