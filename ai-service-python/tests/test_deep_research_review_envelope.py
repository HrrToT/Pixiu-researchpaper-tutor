from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import BudgetExhaustedError
from services.deep_research.experiment_review_envelope import build,enabled,COMMON,WORKFLOW,DATA,AUDIT
from services.deep_research.tools import BudgetedSemanticChecker,TrackedLLMInvoker
from services.deep_research.execution_materialization import verification_claim_view
from test_deep_research_shared_experiment_repair import inputs,json_after
from test_deep_research_direct_audit_fields import analysis_and_verdict


def args(role='steps',question='Compare two groups with and without one stage.'):
    rows=inputs()[0]['claims'];target=next(c for c in rows if c['designRole']==role)
    return dict(claims_text=json.dumps([verification_claim_view(target)],ensure_ascii=False,separators=(',',':')),
        context=[verification_claim_view(c) for c in rows if c['claimId']!=target['claimId']],
        question=question,evidence_marker='EXACT_EVIDENCE_SLOT',metric_domains=['quality','storage'],config_mode=False)


@pytest.mark.parametrize('version',[None,True,False,0,3,'1'])
def test_exact_server_version_only(version):
    assert not enabled(version,3,inputs()[0]['claims'])


@pytest.mark.parametrize('review_version',[None,True,'3',0,2,4])
def test_does_not_reinterpret_other_review_versions(review_version):
    assert not enabled(1,review_version,inputs()[0]['claims'])


def test_facts_unversioned_proposals_and_empty_targets_keep_legacy_view():
    rows=inputs()[0]['claims'];assert enabled(1,3,rows)
    for replacement in ({**rows[0],'kind':'reported'},{**rows[0],'designContractVersion':True}):
        assert not enabled(1,3,[replacement])
    assert not enabled(1,3,[])


@pytest.mark.parametrize('role',['groups','controls','data','budget','steps','metrics','analysis','hypothesis','limits'])
def test_entire_original_target_context_question_and_choices_survive(role):
    kw=args(role,question='Original α and literal system words: '+COMMON)
    before=deepcopy(kw);prompt=build(**kw)
    assert json_after(prompt,'Claims:\n')==json.loads(kw['claims_text'])
    assert json_after(prompt,'Other proposed statements, for consistency only (not evidence and not verdict targets):\n')==kw['context']
    assert json_after(prompt,'Original research question (objective, not evidence):\n')==kw['question']
    assert kw['evidence_marker'] in prompt and kw==before
    assert WORKFLOW in prompt  # Keep full state/compatibility checks even for shared definitions.
    if role not in {'hypothesis','limits'}:assert AUDIT in prompt


def test_skeleton_and_allowed_fields_remain_role_specific():
    text=build(**args('data'))
    skeleton=json_after(text,'Exact per-target response skeleton:\n')
    assert len(skeleton)==1 and skeleton[0]['dataAvailability'] is None
    assert set(skeleton[0]['designAudit'])=={'scenes','split','seeds','sampling_unit'}
    assert DATA in text and 'not original camera IDs' in text
    text=build(**args('steps'))
    roots=json_after(text,'Allowed slot roots (under executionSpec, source role required):\n')
    assert 'baseline_acquisition' in roots and 'component_creation' in roots
    assert 'optimizer_settings' not in roots


def test_factorial_reference_cannot_be_lost_by_claiming_a_single_toggle():
    kw=args('analysis',question='两组，跳过或执行第2阶段，比较整个阶段。')
    # Only a question AND an actual one-factor configuration permit projection.
    groups=next(c for c in kw['context'] if c['designRole']=='groups')
    groups['executionSpec']['factors']=groups['executionSpec']['factors'][:1]
    assert 'Conditional A effects:' not in build(**kw)
    assert 'WHOLE' in build(**kw) or 'whole-stage' in build(**kw)
    groups['executionSpec']['factors'].append(deepcopy(groups['executionSpec']['factors'][0]))
    assert 'Conditional A effects:' in build(**kw)
    kw['question']='四组，两因素的独立与交互效应。'
    assert 'Interaction I=' in build(**kw)


class Capture(TrackedLLMInvoker):
    def __init__(self,limit=32000):
        self.sent=[];self.limit=limit

    def prompt_byte_limit(self,*_):return self.limit

    def uses_verification_input_contract(self,*_):return True

    def __call__(self,**request):
        targets=json_after(request['prompt'],'Claims:\n');self.sent.append(request)
        return {'content':json.dumps([{'claimId':c['claimId'],'status':'failed',
            'reason':'Controlled fixture; no scientific approval.'} for c in targets])}


def checker(capture):
    return BudgetedSemanticChecker(capture,'offline',prospective_review=3,prospective_envelope=1,
        configuration_consistency=2,research_question='Compare a proposed experiment.',metric_domains=['quality'])


def target_with_source(cid,source,quote_size):
    claim,_=analysis_and_verdict();claim['claimId']=cid;claim['evidenceRefs']=[source]
    evidence={'evidenceId':source,'quote':source+' α'*quote_size,'accessLevel':'fulltext',
        'sourceWorkId':'work:'+source,'sourceVersionId':'v4','sourceTitle':'Exact paper '+source,
        'verification':{'literal':'passed'}}
    evidence['sourceContext']='Subject '+source+'. '+evidence['quote']+' Actual original condition.'
    return claim,evidence


def test_splits_before_any_context_stripping_preserving_own_sources_and_all_shared_choices():
    a,ea=target_with_source('a','one',2000);b,eb=target_with_source('b','two',2000)
    # Find a ceiling that admits each full request but not the combined request.
    full=Capture();checker(full)._check_batch([a,b],[ea,eb],[],node='verify_design_science')
    assert len(full.sent)==1
    ceiling=len(full.sent[0]['prompt'].encode())-1000
    capture=Capture(ceiling);before=deepcopy([a,b,ea,eb])
    result=checker(capture)._check_batch([a,b],[ea,eb],[],node='verify_design_science')
    assert len(capture.sent)==2 and [v['claimId'] for v in result]==['a','b']
    for request,e in zip(capture.sent,[ea,eb]):
        packet=json_after(request['prompt'],'Evidence:\n')['evidence'];row=next(iter(packet.values()))
        assert row['quote']==e['quote'] and row['sourceContext']['before'].startswith('Subject '+e['evidenceId'])
        assert row['sourceContext']['after']==' Actual original condition.'
        assert len(packet)==1 and len(request['prompt'].encode())<=ceiling
        assert 'Other proposed statements' in request['prompt']
    assert [a,b,ea,eb]==before


def test_single_unfit_request_never_loses_context_or_calls_provider_and_is_marked_unreviewed():
    a,e=target_with_source('a','one',3000);capture=Capture(1000)
    verdict=checker(capture)._check_batch([a],[e],[],node='verify_design_science')[0]
    assert capture.sent==[] and verdict['status']=='failed' and verdict['executionState']=='not_started'
    assert verdict['reviewInputCapacity']['inputBytes']>1000
    assert verdict['reviewInputCapacity']['maxInputBytes']==1000 and '尚未核验' in verdict['reason']
    from services.deep_research.verification import verify_claims
    result=verify_claims([a],[e],lambda *_:[verdict])
    assert result['accepted']==[]
    assert result['rejected'][0]['reviewInputCapacity']==verdict['reviewInputCapacity']


def test_budget_refusal_is_not_converted_to_a_verdict_or_retried():
    class Refuse(Capture):
        def __call__(self,**request):
            self.sent.append(request)
            raise BudgetExhaustedError('tokens',1,1)
    capture=Refuse()
    claim,e=target_with_source('a','one',3)
    with pytest.raises(BudgetExhaustedError):checker(capture)._check_batch([claim],[e],[],node='verify_design_science')
    assert len(capture.sent)==1


def test_compact_prompt_cannot_approve_a_fabricated_typed_audit_binding():
    claim,verdict=analysis_and_verdict();verdict['designAudit']['effects']['value']={'invented':'value'}
    invoke=Mock(return_value={'content':json.dumps([verdict])})
    check=BudgetedSemanticChecker(invoke,'offline',prospective_review=3,prospective_envelope=1)
    result=check._check_batch([claim],inputs()[2],[],node='verify_design_science')
    assert result[0]['status']=='failed'


def test_complete_configuration_audit_does_not_replace_data_membership_evidence():
    kw=args('data');claim=json.loads(kw['claims_text'])[0]
    verdict={'claimId':claim['claimId'],'status':'passed','reason':'Fixture',
        'designAudit':{slot:{'claimId':claim['claimId'],'path':['executionSpec',field],
            'value':claim['executionSpec'][field]} for slot,field in
            [('scenes','scenes'),('split','split'),('seeds','seeds'),('sampling_unit','independentUnit')]},
        'dataAvailability':None}
    check=BudgetedSemanticChecker(lambda **_:{'content':json.dumps([verdict])},'offline',
        prospective_review=3,prospective_envelope=1)
    result=check._check_batch([claim],inputs()[2],kw['context'],node='verify_design_config')
    assert result[0]['status']=='failed' and '可用数量尚未核实' in result[0]['reason']


def test_wrong_typed_envelope_versions_leave_the_exact_legacy_request_unchanged():
    claim,_=analysis_and_verdict();baseline=[]
    def run(version):
        sent=[]
        def invoke(**request):
            sent.append(request)
            return {'content':json.dumps([{'claimId':claim['claimId'],'status':'failed','reason':'Fixture'}])}
        BudgetedSemanticChecker(invoke,'offline',prospective_review=3,prospective_envelope=version)([claim],inputs()[2])
        return sent
    baseline=run(0)
    for version in (None,True,False,3,'1'):assert run(version)==baseline


@pytest.mark.parametrize('replacement',[None,True,0,1,'2'])
def test_new_prompt_contract_is_server_owned_immutable(tmp_path,replacement):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'runs.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        record,_=facade.create({'workspaceTaskId':'t','operationKey':'k','question':'Propose an experiment',
            'experimentReviewEnvelopeContractVersion':replacement,'deferStart':True},start_async=False)
        assert record['experimentReviewEnvelopeContractVersion']==2
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(record['runId'],lambda r:{**r,'experimentReviewEnvelopeContractVersion':replacement})
    finally:facade.shutdown()
