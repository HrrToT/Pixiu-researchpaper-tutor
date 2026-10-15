from copy import deepcopy
import json

import pytest

from services.deep_research.experiment_deliverable import ensure_experiment_deliverable
from services.deep_research.coverage import validate_plan
from services.deep_research.graph import make_plan_node
from services.deep_research.obligation_purpose import nonblocking_research_obligations
from services.deep_research.design_drafting import synthesis_obligations


QUESTION='先说明论文报告的PSNR及训练机制，再设计两组单场景实验，给出固定条件、预算和指标。'


def plan():
    return [{'itemId':'p','question':'One proposal','obligations':[
        {'obligationId':'authors','question':'What were the author view counts and resolution?',
         'requiredSources':['paper'],'searchQuery':'benchmark original data views',
         'purpose':'answer_requirement','completionCriteria':[{'criterionId':'original','responseType':'identification','requirement':'Original view count'}]},
        {'obligationId':'mechanism','question':'How does the original method train?',
         'requiredSources':['paper'],'searchQuery':'method training'}]}]


def test_original_user_request_is_mandatory_and_support_is_preserved_not_marked_answered():
    original=plan();before=deepcopy(original)
    result=ensure_experiment_deliverable(original,QUESTION,['paper'])
    assert validate_plan(result) and len(result)==len(original)
    main,*support=result[0]['obligations']
    assert main['question']==QUESTION and main['purpose']=='answer_requirement'
    assert main['requiredSources']==['paper'] and 'PSNR' in main['question']
    for old,new in zip(original[0]['obligations'],support):
        assert new['question']==old['question'] and new['searchQuery']==old['searchQuery']
        assert new['requiredSources']==old['requiredSources']
        assert new['purpose']=='supporting_research' and 'status' not in new
    assert original==before
    assert ensure_experiment_deliverable(result,QUESTION,['paper'])==result


def test_auxiliary_benchmark_checklist_does_not_replace_requested_proposal_in_drafting():
    result=ensure_experiment_deliverable(plan(),QUESTION,['paper'])
    rows=synthesis_obligations(result)
    assert rows[0]['question']==QUESTION and rows[0]['completionCriteria']
    assert 'completionCriteria' not in rows[1]
    assert rows[1]['question']==plan()[0]['obligations'][0]['question']


@pytest.mark.parametrize('main_status',['partial','missing','not_required'])
def test_support_cannot_be_exempted_while_original_deliverable_is_unanswered(main_status):
    result=ensure_experiment_deliverable(plan(),QUESTION,['paper'])
    main=result[0]['obligations'][0]['obligationId']
    claims=[{'claimId':'c','text':'A limited proposed comparison.','kind':'proposal'}]
    binding=[{'claimId':'c','excerpt':claims[0]['text']}]
    verdicts=[{'obligationId':'whole','status':'covered','bindings':binding},
              {'obligationId':main,'status':main_status,'bindings':binding},
              {'obligationId':'authors','status':'not_required','reason':'Author-specific original counts are unrelated to this proposed configuration.',
               'requestExcerpt':QUESTION,'bindings':binding}]
    assert not nonblocking_research_obligations(result,QUESTION,claims,verdicts,'whole')


def test_identifier_collision_does_not_let_generated_metadata_suppress_the_real_request():
    original=plan();original[0]['obligations'][0]['obligationId']='experiment_deliverable'
    result=ensure_experiment_deliverable(original,QUESTION,['paper'])
    assert result[0]['obligations'][0]['obligationId']=='experiment_deliverable_new'
    assert result[0]['obligations'][0]['question']==QUESTION


@pytest.mark.parametrize('enabled',[False,True])
def test_only_new_snapshot_opt_in_changes_experiment_plan_semantics(enabled):
    record={'question':QUESTION,'state':{'outputKind':'experiment_design'},'materials':[{'materialId':'paper'}]}
    if enabled:record['experimentPlanContractVersion']=1
    def update(run,change,**kwargs):
        nonlocal record
        record=change(record);return record
    make_plan_node(lambda *args:{'content':json.dumps(plan())},update,validate_plan)({'run_id':'r'})
    obligations=record['state']['plan'][0]['obligations']
    assert any(o.get('deliverableContractVersion')==1 for o in obligations)==enabled
    if enabled:
        main=next(o for o in obligations if o.get('deliverableContractVersion')==1)
        assert main['question']==QUESTION and main['purpose']=='answer_requirement'


def test_short_request_does_not_fabricate_supporting_scope_exemption():
    result=ensure_experiment_deliverable(plan(),'设计实验',['paper'])
    assert result[0]['obligations'][1]['purpose']=='answer_requirement'
