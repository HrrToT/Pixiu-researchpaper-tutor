from copy import deepcopy
import json
import pytest
from services.deep_research.contracts import DeepResearchError
from services.deep_research.joint_assessment import _verdicts,_review_units
from test_deep_research_joint_assessment import fixture,Memory,execute,units


def setup(version=4):
    record=fixture(('a',));record['jointEvidenceContractVersion']=version
    first=record['state']['plan'][0]['obligations'][0]
    second=deepcopy(first);second.update(obligationId='process',question='如何计算更新',requestExcerpt='如何计算更新',
        completionCriteria=[{'criterionId':'how','requirement':'如何计算更新','responseType':'explanation'}])
    record['state']['plan'][0]['obligations'].append(second)
    return Memory(record)


def response(prompt,bad=True):
    result=[]
    for unit in units(prompt):
        row={'unitId':unit['unitId'],'ready':True,'evidenceIds':unit['evidenceIds']}
        if unit.get('processRequired'):
            row['processLinks']=[{'input':{'request':'计算'},'operation':{'id':('op1' if bad else unit['evidenceIds'][0]),
                'field':'quote','excerpt':'We evaluate a using our GPU platform and a fixed configuration.'},
                'output':{'request':'更新'}}]
        result.append(row)
    return {'content':json.dumps(result)}


def received(memory):
    return next(s for rounds in memory.record['state']['jointAssessment']['scopes'].values() for s in rounds.values() if s['status']=='received')


def test_invalid_process_unit_cannot_erase_valid_peer_or_become_ready_on_reopen():
    memory=setup();before=deepcopy(memory.record['state']['evidence']);calls=[]
    def invoke(r,n,p,o):calls.append((p,o));return response(p)
    result=execute(memory,invoke)
    assert [g['obligationId'] for g in result['gaps']]==['process']
    saved=received(memory);assert saved['responseAudit']=={'version':1,'status':'checked','validUnits':['G1'],'invalidUnits':['G2']}
    assert len(_verdicts(saved))==1 and memory.record['state']['assessmentStatus']=='unchecked'
    execute(memory,lambda *_:pytest.fail('Do not resend received unit failures'))
    assert len(calls)==1 and calls[0][1]['max_tokens']==1536
    assert [e['quote'] for e in memory.record['state']['evidence']]==[e['quote'] for e in before]
    assert all('process' not in e['obligationIds'] for e in memory.record['state']['evidence'])
    assert 'EXACTLY id,field,excerpt' in calls[0][0]


def test_legacy_batch_failure_remains_atomic_with_exact_archived_request():
    memory=setup(3);result=execute(memory,lambda r,n,p,o:response(p))
    assert len(result['gaps'])==2 and _verdicts(received(memory)) is None
    saved=deepcopy(received(memory));assert 'responseAudit' not in saved
    execute(memory,lambda *_:pytest.fail('No legacy resend'))
    assert received(memory)==saved


@pytest.mark.parametrize('mode',['duplicate','missing','foreign','nonobject','truncated'])
def test_unknown_envelope_ownership_never_partially_approves(mode):
    memory=setup();execute(memory,lambda r,n,p,o:response(p));saved=deepcopy(received(memory));rows=json.loads(saved['content'])
    if mode=='duplicate':rows[1]['unitId']=rows[0]['unitId']
    elif mode=='missing':rows.pop()
    elif mode=='foreign':rows[1]['unitId']='G99'
    elif mode=='nonobject':rows[1]=None
    else:saved['finishReason']='length'
    saved['content']=json.dumps(rows)
    decisions,audit=_review_units(saved)
    assert decisions is None and audit['status']=='invalid_envelope' and not audit['validUnits']


@pytest.mark.parametrize('bad',['foreign_ref','missing_process','extra_field','string_bool','mixed_role','overlap'])
def test_each_unit_keeps_strict_source_process_and_schema_checks(bad):
    memory=setup()
    def invoke(r,n,p,o):
        rows=json.loads(response(p,bad=False)['content']);row=rows[1]
        if bad=='foreign_ref':row['evidenceIds']=['E99']
        elif bad=='missing_process':row.pop('processLinks')
        elif bad=='extra_field':row['approved']=True
        elif bad=='string_bool':row['ready']='true'
        elif bad=='mixed_role':row['processLinks'][0]['input']['field']='quote'
        else:row['processLinks'][0]['output']=row['processLinks'][0]['input']
        return {'content':json.dumps(rows)}
    assert [g['obligationId'] for g in execute(memory,invoke)['gaps']]==['process']


def test_valid_process_and_false_decision_are_distinct_from_invalid_response():
    for ready in (True,False):
        memory=setup()
        def invoke(r,n,p,o):
            rows=json.loads(response(p,bad=False)['content'])
            if not ready:rows[1].update(ready=False,evidenceIds=[],processLinks=[])
            return {'content':json.dumps(rows)}
        result=execute(memory,invoke)
        assert bool(result['gaps']) is (not ready)
        assert memory.record['state']['assessmentStatus']=='checked'
        assert received(memory)['responseAudit']['invalidUnits']==[]


def test_saved_unit_audit_cannot_be_tampered_to_upgrade_invalid_source_binding():
    memory=setup();execute(memory,lambda r,n,p,o:response(p));saved=received(memory)
    saved['responseAudit']['invalidUnits']=[]
    with pytest.raises(DeepResearchError):execute(memory,lambda *_:pytest.fail('No send on corrupt audit'))
