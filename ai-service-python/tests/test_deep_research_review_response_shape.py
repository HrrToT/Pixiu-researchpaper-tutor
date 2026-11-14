import json
from copy import deepcopy

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.experiment_review_envelope import build
from services.deep_research.structured_output import normalize, messages
from services.deep_research.tools import BudgetedSemanticChecker
from test_deep_research_review_envelope import args, Capture, target_with_source
from test_deep_research_shared_experiment_repair import json_after


SKELETON='Exact response skeleton (fill EVERY target, including failures; even one target stays inside items):\n'


@pytest.mark.parametrize('role',['groups','controls','data','budget','steps','metrics','analysis','hypothesis','limits'])
def test_schema_and_native_transport_agree_without_rewriting_target_or_context(role):
    kw=args(role);before=deepcopy(kw)
    old=build(**kw,version=2);new=build(**kw,version=3)
    assert json_after(new,SKELETON)=={'items':json_after(old,'Exact per-target response skeleton:\n')}
    for marker in ['Claims:\n','Other proposed statements, for consistency only (not evidence and not verdict targets):\n',
        'Original research question (objective, not evidence):\n']:
        assert json_after(new,marker)==json_after(old,marker)
    assert 'Return ONLY a JSON array' not in new
    assert 'Rejected context policy:' in new and kw['evidence_marker'] in new
    assert '{"items":[]}' in messages('verify_design_config',new,9,prospective=True)[0]['content']
    assert kw==before


@pytest.mark.parametrize('count',[1,2])
@pytest.mark.parametrize('shape',['items','single','missing','duplicate','extra'])
def test_only_complete_unique_target_verdicts_are_usable_after_native_normalization(count,shape):
    pairs=[target_with_source('c'+str(i),'E'+str(i),2) for i in range(count)]
    claims=[c for c,e in pairs];evidence=[e for c,e in pairs]
    verdicts=[{'claimId':c['claimId'],'status':'failed','reason':'Unresolved; no scientific approval.'} for c in claims]
    if shape=='missing':verdicts.pop()
    if shape=='duplicate':verdicts.append(deepcopy(verdicts[0]))
    if shape=='extra':verdicts.append({**verdicts[0],'claimId':'outside-targets'})
    payload=verdicts[0] if shape=='single' else {'items':verdicts}

    class Wire(Capture):
        def __call__(self,**request):
            self.sent.append(request)
            skeleton=json_after(request['prompt'],SKELETON)
            assert [c['claimId'] for c in skeleton['items']]==[c['claimId'] for c in claims]
            return normalize(request['node'],{'content':json.dumps(payload),'finishReason':'stop'})

    capture=Wire();checker=BudgetedSemanticChecker(capture,'offline',prospective_review=3,prospective_envelope=3)
    if shape=='items':
        result=checker._check_batch(claims,evidence,[],node='verify_design_science')
        assert len(result)==count and all(c['status']=='failed' for c in result)
    else:
        with pytest.raises(DeepResearchError):
            checker._check_batch(claims,evidence,[],node='verify_design_science')
    assert len(capture.sent)==1  # Never resend an invalid response.
