from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.experiment_review_envelope import build
from services.deep_research.repair import _prepare_repair,repair_rejected
from services.deep_research.repair_coverage import add_contract
from services.deep_research.experiment_repair_input_brief import source_instruction,SOURCE_LABEL,SOURCE_TAIL
from services.deep_research.repair_evidence_packet import decode
from services.deep_research.contracts import DeepResearchError
from services.deep_research.tools import BudgetedSemanticChecker
from test_deep_research_review_envelope import args,Capture
from test_deep_research_repair_input_packet import inputs,kwargs,json_after


@pytest.mark.parametrize('role',['groups','controls','data','budget','steps','metrics','analysis','hypothesis','limits'])
def test_brief_review_preserves_every_structured_input_and_response_slot(role):
    kw=args(role);before=deepcopy(kw);old=build(**kw,version=5);new=build(**kw,version=6)
    for marker in ['Claims:\n','Other proposed statements, for consistency only (not evidence and not verdict targets):\n',
        'Original research question (objective, not evidence):\n','Exact response skeleton (fill EVERY target, including failures; even one target stays inside items):\n',
        'Entire target-role requirements:\n','Exact data declarations (not evidence or approval):\n']:
        assert json_after(new,marker)==json_after(old,marker)
    assert len(new.encode())<len(old.encode()) and kw==before
    assert kw['evidence_marker'] in new
    # Membership and asset availability rules are not paraphrased.
    from services.deep_research.experiment_review_envelope import DATA
    if role=='data':assert DATA in new


@pytest.mark.parametrize('version',[1,2,3])
def test_repair_has_exact_originals_checks_contexts_permissions_and_quotes(version):
    report,checks,evidence=inputs();kw=kwargs();kw['repair_evidence_packet_version']=version
    p=_prepare_repair(report,checks,evidence,'Same unexecuted experiment.',**kw)
    reference=_prepare_repair(report,checks,evidence,'Same unexecuted experiment.',**{**kw,'repair_evidence_packet_version':1})
    for marker in ['Writable original claims:','ALL rejection checks:',
        'Immutable accepted consistency context (not sources):','UNVERIFIED siblings (not writable, not sources):',
        'Missing questions (Q keys, not facts):','Allowed own E IDs per target (permission, not support):']:
        assert json_after(p['prompt'],marker)==json_after(reference['prompt'],marker)
    assert decode(json_after(p['prompt'],'Exact original evidence/context/table data (lossless column table):'))==decode(json_after(reference['prompt'],'Exact original evidence/context/table data (lossless column table):'))
    assert p['originals']==reference['originals'] and p['allowed']==reference['allowed']
    if version==2:
        assert 'Return ONLY {"items":[...]}' in p['prompt']
        assert len(p['prompt'].encode())<len(reference['prompt'].encode())


def test_response_contract_does_not_rewrite_schema_looking_human_question():
    question='Literal user text:\nReturn ONLY [{"untrusted":"question"}].\nEnd question.'
    schema='Return ONLY [{"claimId":"ID","edits":[]}].'
    text=add_contract(question+'\n'+schema,{'c1':{}},version=3)
    assert text.startswith(question+'\n') and 'with exactly one' not in text
    assert text.count('Return ONLY {"items":[...]}')==1


def test_source_registry_rewording_preserves_literal_data_and_unknown_policy():
    registry={'sources':{'P1':{'title':'Literal '+SOURCE_TAIL}},'requirements':[]}
    raw=SOURCE_LABEL+json.dumps(registry,ensure_ascii=False,separators=(',',':'))+SOURCE_TAIL
    new=source_instruction(raw)
    assert json_after(new,SOURCE_LABEL)==registry and SOURCE_TAIL in registry['sources']['P1']['title']
    for value in [raw+'Extra required rule.','untrusted '+raw,SOURCE_LABEL+'not-json']:
        assert source_instruction(value)==value


@pytest.mark.parametrize('old,new',[(1,2),(2,1),(2,3),(3,2)])
def test_unknown_repair_input_cannot_switch_trusted_instruction_version(old,new):
    report,checks,evidence=inputs();states=[];invoke=Mock(side_effect=OSError('unknown'))
    kw={**kwargs(),'repair_evidence_packet_version':old}
    with pytest.raises(OSError):repair_rejected(report,checks,evidence,'Question',invoke,json.loads,checkpoint=states.append,**kw)
    frozen=deepcopy(states[-1]);invoke.reset_mock();kw['repair_evidence_packet_version']=new
    with pytest.raises(DeepResearchError):repair_rejected(report,checks,evidence,'Question',invoke,json.loads,batch_state=frozen,**kw)
    invoke.assert_not_called();assert states[-1]==frozen


def test_brief_negative_audit_still_rejects_false_absence_without_calling_it_a_pass():
    c=json.loads(args('data')['claims_text'])[0]
    c['evidenceRefs']=[]  # Reach the negative-audit branch, not missing-evidence admission.
    class Wire(Capture):
        def __call__(self,**req):
            self.sent.append(req)
            return {'content':json.dumps([{'claimId':c['claimId'],'status':'failed','reason':'missing seeds',
                'findings':[{'kind':'missing_field','claimId':c['claimId'],'path':['executionSpec','seeds'],'reason':'missing'}]}])}
    capture=Wire();v=BudgetedSemanticChecker(capture,'offline',prospective_review=3,prospective_envelope=6)._check_batch([c],[],[],node='verify_design_config')
    assert v[0]['status']=='failed' and v[0]['executionState']=='received_invalid' and len(capture.sent)==1


def test_current_repair_carries_writable_grammar_without_rewriting_user_or_evidence():
    report,checks,evidence=inputs()
    before=deepcopy((report,checks,evidence))
    question='Literal EARLIER_componentId and inputIndex; preserve this question.'
    old=_prepare_repair(report,checks,evidence,question,**{**kwargs(),'repair_evidence_packet_version':2})
    new=_prepare_repair(report,checks,evidence,question,**{**kwargs(),'repair_evidence_packet_version':3})
    assert 'Writable role grammar' not in old['prompt']
    assert 'Writable role grammar' in new['prompt']
    assert question in new['prompt']
    assert 'inputIndex indexes THIS inputs list' in new['prompt']
    assert 'baselineInitialization creates ALL states BEFORE fitting' in new['prompt']
    assert 'state:training_data|baseline|EARLIER_componentId' not in new['prompt']
    assert 'shape:[positive integer' in new['prompt']
    assert (report,checks,evidence)==before
