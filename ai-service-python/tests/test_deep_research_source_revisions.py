from copy import deepcopy
import json
from urllib.parse import parse_qs,urlsplit
from unittest.mock import Mock

import pytest

from services.deep_research.coverage import validate_plan
from services.deep_research.external import AcademicAcquisition
from services.deep_research.graph import make_plan_node,make_acquire_node
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.source_revisions import bind,explicit_revisions,normalize_plan
from services.deep_research_academic import AcademicPolicy,AcademicSourceClient
from test_deep_research_exact_discovery import atom


def plan(refs):
    return [{'itemId':'i','question':'Explain the mechanism','dependencies':[],
             'obligations':[{'obligationId':'o','question':'Explain the mechanism','requiredSources':refs}]}]


@pytest.mark.parametrize('reference',['arXiv:2406.01467v1','https://arxiv.org/abs/2406.01467v1',
    'https://arxiv.org/pdf/2406.01467v1.pdf','2406.01467v1','arxiv:astro-ph/0612345v2',
    '读arXiv:2406.01467v1的原文'])
def test_literal_revision_references_are_not_replaced_by_latest(reference):
    revisions=explicit_revisions('读取 '+reference+' 的原文。')
    assert len(revisions)==1 and list(revisions.values())[0][0].endswith(('v1','v2'))
    before=deepcopy(revisions)
    assert bind(list(revisions), '读取 '+reference+' 的原文。')==list(revisions.values())[0]
    assert revisions==before


@pytest.mark.parametrize('model_reference',['arxiv:2406.01467','arxiv:2406.01467v1','arxiv:2406.01467v2'])
def test_real_plan_then_acquisition_requests_the_literal_version(tmp_path,model_reference):
    question='读取 RaDe-GS（arXiv:2406.01467v1）的原文，解释其机制。'
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t','question':question,'exactDiscoveryContractVersion':2,
                     'sourcePolicy':{'mode':'external_only'},'materials':[], 'state':{'outputKind':'claim_verification'}})
    repo.begin_execution('r');generated=plan([model_reference]);before=deepcopy(generated)
    def update(rid,change,**kw):return repo.update_run(rid,change)
    invoke=Mock(return_value={'content':json.dumps(generated)})
    assert not make_plan_node(invoke,update,validate_plan)({'run_id':'r'}).get('error_code')
    saved=repo.require_run('r')
    assert saved['question']==question and saved['state']['plan'][0]['obligations'][0]['requiredSources']==['arxiv:2406.01467v1']
    assert saved['state']['planSourceRevisionNormalization']['requestedRevisions']=={'arxiv:2406.01467':['arxiv:2406.01467v1']}
    paths=[]
    def transport(host,path,limit):
        paths.append((host,path))
        return ('application/atom+xml',atom(['2406.01467v1','2406.01467v2'])) if host=='export.arxiv.org' else ('application/pdf',b'%PDF-frozen-fixture')
    client=AcademicSourceClient(AcademicPolicy(enabled=True,mode='external_only',allow_fulltext=True),transport)
    client._parse_fulltext=Mock(return_value=[{'page':1,'text':'The requested original method retains general Gaussian primitives and rasterizes depth and normal maps.'}])
    acquire=AcademicAcquisition(repo,repo.complete_call,client_factory=lambda _:client)
    make_acquire_node(lambda *_:pytest.fail('No local retrieval'),lambda *_:True,update,external_acquire=acquire)({'run_id':'r'})
    assert parse_qs(urlsplit(paths[0][1]).query)['id_list']==['2406.01467v1']
    assert paths[1]==('arxiv.org','/pdf/2406.01467v1')
    assert {s['versionId'] for s in repo.require_run('r')['state']['sources']}=={'arxiv:2406.01467v1'}
    assert generated==before and invoke.call_count==1


def test_acquisition_rechecks_literal_pin_when_target_is_unversioned(tmp_path):
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t','question':'Read arxiv:2308.04079v1','exactDiscoveryContractVersion':2,'sourcePolicy':{'mode':'external_only'}});repo.begin_execution('r')
    paths=[]
    def transport(host,path,limit):paths.append(path);return 'application/atom+xml',atom(['2308.04079v2'])
    client=AcademicSourceClient(AcademicPolicy(enabled=True,mode='external_only'),transport)
    result=AcademicAcquisition(repo,repo.complete_call,client_factory=lambda _:client)('r',[{'obligationId':'o','query':'mechanism','requiredSources':['arxiv:2308.04079']}])
    assert result==[] and len(paths)==1 and parse_qs(urlsplit(paths[0]).query)['id_list']==['2308.04079v1']


def test_multiple_revisions_and_empty_model_sources_preserve_explicit_inputs():
    question='Compare arxiv:2308.04079v1 and arxiv:2308.04079v3'
    assert bind(['arxiv:2308.04079'],question)==['arxiv:2308.04079v1','arxiv:2308.04079v3']
    result,audit=normalize_plan(plan([]),question,[],[])
    assert result[0]['obligations'][0]['requiredSources']==['arxiv:2308.04079v1','arxiv:2308.04079v3']
    with pytest.raises(ValueError):bind(['arxiv:2308.04079v2'],question)
    with pytest.raises(ValueError):normalize_plan(plan(['arxiv:2406.01467']),question,[],[])


def test_original_contract_keeps_its_saved_planning_behavior():
    record={'question':'Read arxiv:2308.04079v1','exactDiscoveryContractVersion':1,
            'sourcePolicy':{'mode':'external_only'},'materials':[],'state':{'outputKind':'claim_verification'}}
    def update(rid,change,**kw):
        nonlocal record
        record=change(record);return deepcopy(record)
    make_plan_node(Mock(return_value={'content':json.dumps(plan(['arxiv:2308.04079v1']))}),update,validate_plan)({'run_id':'r'})
    assert record['state']['plan'][0]['obligations'][0]['requiredSources']==['arxiv:2308.04079']
    assert 'planSourceRevisionNormalization' not in record['state']


def test_local_material_identity_is_never_relabelled_as_a_public_revision():
    original=plan(['local-content-hash'])
    result,_=normalize_plan(original,'Read arxiv:2406.01467v1',['local-content-hash'],['local-content-hash'])
    assert result==original


def test_fulltext_identity_cannot_replace_successful_pinned_metadata(tmp_path):
    from services.deep_research.contracts import DeepResearchError
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    repo.create_run({'runId':'r','taskId':'t','question':'Read arxiv:2308.04079v1','exactDiscoveryContractVersion':2,'sourcePolicy':{'mode':'external_only'}});repo.begin_execution('r')
    client=AcademicSourceClient(AcademicPolicy(enabled=True,mode='external_only',allow_fulltext=True),lambda *_:('application/atom+xml',atom(['2308.04079v1'])))
    client.fetch_fulltext=Mock(return_value={'workId':'arxiv:2308.04079','versionId':'arxiv:2308.04079v2','arxivId':'2308.04079v2','accessLevel':'fulltext'})
    with pytest.raises(DeepResearchError,match='版本不一致'):
        AcademicAcquisition(repo,repo.complete_call,client_factory=lambda _:client)('r',[{'obligationId':'o','query':'mechanism','requiredSources':['arxiv:2308.04079v1']}])
    client.fetch_fulltext.assert_called_once_with('2308.04079v1')


@pytest.mark.parametrize('both_versions',[False,True])
def test_joint_readiness_does_not_conflate_two_revisions_of_the_same_work(both_versions):
    from services.deep_research.verification import make_evidence
    from test_deep_research_joint_assessment import fixture,Memory,execute,ready_response
    record=fixture();work='arxiv:2308.04079';versions=[work+'v1',work+'v3']
    evidence=[]
    for version in versions if both_versions else versions[1:]:
        quote='Reported method in '+version
        evidence.append(make_evidence({'workId':work,'versionId':version,'contentHash':version+'-hash','accessLevel':'fulltext'},quote,quote,location={'page':1},obligation_ids=[]))
    record['materials']=[];record['state']['sources']=[{'workId':work,'versionId':v} for v in versions]
    record['state']['evidence']=evidence
    for o,version in zip(record['state']['plan'][0]['obligations'],versions):o['requiredSources']=[version]
    memory=Memory(record)
    result=execute(memory,lambda run,node,prompt,options:ready_response(prompt))
    if both_versions:assert not result['gaps'] and result['stop_reason']=='covered'
    else:assert any(g['sourceWorkId']==versions[0] for g in result['gaps'])
