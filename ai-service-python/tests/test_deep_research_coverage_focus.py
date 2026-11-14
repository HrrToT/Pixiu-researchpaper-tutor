from copy import deepcopy
import json
import pytest
from services.deep_research.request_coverage import prompt,focus_answer,DECISION_FOCUS
from services.deep_research.final_coverage import audit_final_answer
from test_deep_research_request_coverage import QUESTION,PLAN,CLAIMS,EVIDENCE,response


def test_focus_moves_exact_full_context_after_policies_without_replacing_data_markers():
    q='问题中也有 Accepted final claims: 和 Decision inputs 标记'
    req=[{'obligationId':'o','checks':[]}]
    claims=[{'claimId':'x','text':'支持该有界结论；不能推出全部场景。','conditions':{'literal':'Fixed checks:'}}]
    meta={'label':'Available evidence'}
    base=prompt(q,req,claims,meta,'UNIQUE_EVIDENCE_SLOT','policy Before marking covered, enumerate ignored')+'\nLAST_POLICY'
    out=focus_answer(base,q,req,claims,meta)
    assert out.index('LAST_POLICY')<out.index('Decision inputs (fixed request and complete accepted answer):')
    tail=out.split('Decision inputs (fixed request and complete accepted answer):\n',1)[1]
    assert tail.startswith('Question: '+q+'\n')
    for label,obj in [('Fixed checks (requirements, never paper facts): ',req),('Accepted final claims: ',claims),('Server-rendered answer metadata: ',meta)]:
        assert json.JSONDecoder().raw_decode(tail.split('\n'+label,1)[1])[0]==obj
    assert out.count('UNIQUE_EVIDENCE_SLOT')==1
    assert 'no automatic coverage' in out and DECISION_FOCUS in out
    with pytest.raises(ValueError):focus_answer(base,q+'changed',req,claims,meta)


@pytest.mark.parametrize('version',[1,2,3])
def test_audit_preserves_independent_partial_and_joint_answer_input(version):
    before=deepcopy((PLAN,CLAIMS,EVIDENCE));sent=[]
    def invoke(*args,**kwargs):
        text=args[2];sent.append(text)
        fixed=json.JSONDecoder().raw_decode(text.split('Fixed checks (requirements, never paper facts): ',1)[1])[0]
        wire=json.JSONDecoder().raw_decode(text.split('Accepted final claims: ',1)[1])[0]
        assert [c['text'] for c in wire]==[c['text'] for c in CLAIMS]
        raw=response(fixed);raw[0]['checks'][1]['status']='partial'
        raw[0]['checks'][1]['reason']='Fixture: a required explanation is still missing.'
        return {'content':json.dumps(raw)}
    result=audit_final_answer('r',QUESTION,PLAN,CLAIMS,EVIDENCE,invoke,json.loads,diagnostics=True,request_contract=version,literal_dimensions=True,claim_check=True)
    assert result['requestCoverageContractVersion']==version
    assert result['gaps'] and result['verdicts'][0]['status']=='partial'
    assert before==(PLAN,CLAIMS,EVIDENCE)
    assert (DECISION_FOCUS in sent[0])==(version==3)
    if version==3:
        assert sent[0].index('Available evidence')<sent[0].index('Fixed checks (requirements, never paper facts): ')
        assert sent[0].index('For this claim-check request')<sent[0].index('Accepted final claims: ')
    else:assert sent[0].index('Accepted final claims: ')<sent[0].index('Available evidence')


def test_legacy_request_prompt_is_byte_identical():
    import hashlib
    args=('question', [{'obligationId': 'o'}], [{'claimId': 'c', 'text': 'answer'}], {'pointCount': 1}, 'EVIDENCE', 'quality Before marking covered, enumerate redundant')
    assert hashlib.sha256(prompt(*args).encode()).hexdigest()=='c77c7bff7b10243db0ed49c700d28943a15dd3259871b9d5964c5622634ae3e0'
