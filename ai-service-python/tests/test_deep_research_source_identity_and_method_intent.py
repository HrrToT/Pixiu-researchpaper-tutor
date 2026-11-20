from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.publication_identity import from_verified_pages, validated, GUIDANCE
from services.deep_research.method_details import include_method_details
from services.deep_research.extraction_priority import prioritize_extraction_passages
from services.deep_research.graph import make_acquire_node,make_read_node
from services.deep_research.extraction import make_batched_extract_node
from services.deep_research.verification import make_evidence
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.contracts import DeepResearchError
from test_deep_research_method_details import passage
from test_deep_research_local_sources import fixture as local_fixture


def identity():
    return from_verified_pages({'contentHash':'a'*64},[{'page':1,'text':'Title\narXiv:2403.01444v4 [cs.CV]'}])


def test_revision_requires_the_actual_single_first_page_stamp_never_the_filename():
    m={'contentHash':'a'*64,'title':'Paper v9','materialId':'paper-v9.pdf'}
    assert from_verified_pages(m,[{'page':1,'text':'No stamp'},{'page':2,'text':'arXiv:2403.01444v9'}]) is None
    assert from_verified_pages(m,[{'page':1,'text':'arXiv:2403.01444v4 arXiv:2403.01444v3'}]) is None
    assert identity()['revision']=='v4'
    assert validated(identity(),'a'*64)==identity()
    for key,value in [('revision','v9'),('workId','arxiv:2300.00000'),('physicalPage',True),
                      ('origin','model'),('literalStamp','made up')]:
        bad={**identity(),key:value};assert validated(bad,'a'*64) is None
    assert validated(identity(),'b'*64) is None


def test_local_revision_read_is_hashed_owned_cached_and_rechecks_revocation(monkeypatch):
    local,get,parse,validate=local_fixture(monkeypatch)
    local.repo.require_run.return_value['sourcePrecisionContractVersion']=4
    parse.return_value[0]['text']='arXiv:2403.01444v4'
    rows=[{'sourceId':'s','pdfId':'p','text':'body'}];before=deepcopy(rows)
    found=local._stamp_identity(rows,'p')
    assert found[0]['publicationIdentity']['revision']=='v4' and rows==before
    assert local._stamp_identity(rows,'p')==found and get.call_count==parse.call_count==1
    validate.return_value=False
    with pytest.raises(DeepResearchError,match='范围'):
        local._stamp_identity(rows,'p')
    assert get.call_count==1


def test_revision_metadata_cannot_survive_changed_pdf_or_forbidden_read(monkeypatch):
    local,get,parse,_=local_fixture(monkeypatch,changed=True)
    local.repo.require_run.return_value['sourcePrecisionContractVersion']=4
    with pytest.raises(DeepResearchError,match='快照'):
        local._stamp_identity([{'sourceId':'s'}],'p')
    parse.assert_not_called()
    local,get,parse,_=local_fixture(monkeypatch)
    local.repo.require_run.return_value['sourcePrecisionContractVersion']=4
    get.return_value.status_code=403
    with pytest.raises(DeepResearchError):local._stamp_identity([{'sourceId':'s'}],'p')
    assert get.call_count==1


def test_optional_revision_failure_is_not_repeated_and_never_guessed(monkeypatch):
    local,get,parse,_=local_fixture(monkeypatch)
    local.repo.require_run.return_value['sourcePrecisionContractVersion']=4
    get.return_value.status_code=503
    rows=[{'sourceId':'s','text':'Paper v9'}]
    assert local._stamp_identity(rows,'p')==rows==local._stamp_identity(rows,'p')
    assert get.call_count==1 and parse.call_count==0


@pytest.mark.parametrize('foreign',[False,True])
def test_publication_identity_survives_acquire_read_extract_but_not_model_invention(foreign):
    quote='Our method uses multi-view video streams with calibrated camera poses as input.';pub=identity()
    if foreign:pub['contentHash']='b'*64
    record={'runId':'r','materials':[{'materialId':'p','contentHash':'a'*64,'versionId':'owned-v','title':'Paper'}],
        'state':{'plan':[{'itemId':'i','obligations':[{'obligationId':'o','question':'What inputs?','requiredSources':['p']}]}]},
        'extractionPriorityVersion':5}
    def update(_id,change,**_):
        nonlocal record
        record=change(deepcopy(record));return deepcopy(record)
    retrieve=lambda *_args,**_kwargs:[{'sourceId':'s','pdfId':'p','text':quote,'location':{'page':4},'publicationIdentity':pub}]
    acquired=make_acquire_node(retrieve,lambda *_:True,update)({'run_id':'r'})
    make_read_node(lambda *_:{'pages':[{'page':4,'text':quote}],'accessLevel':'fulltext'},lambda *_:True,update)({'run_id':'r',**acquired})
    invoke=Mock(return_value={'content':json.dumps([{'sourceId':'s','quote':quote,'obligationIds':['o'],
        'sourcePublicationIdentity':{'revision':'v99'}}])})
    make_batched_extract_node(invoke,make_evidence,lambda *_:True,update)({'run_id':'r'})
    assert record['state']['evidence'], (record['state'].get('sources'),record['state'].get('readResults'),invoke.call_count)
    ev=record['state']['evidence'][0]
    if foreign:
        assert 'sourcePublicationIdentity' not in ev
    else:
        assert ev['sourcePublicationIdentity']==identity() and ev['sourceVersionId']=='owned-v'
        checker_invoke=Mock(return_value={'content':json.dumps([{'claimId':'c','status':'failed','reason':'Body does not support method claim'}])})
        result=BudgetedSemanticChecker(checker_invoke,'r')([{'claimId':'c','kind':'reported','text':'Wrong method fact','evidenceRefs':[ev['evidenceId']]}],[ev])
        assert result[0]['status']=='failed' and GUIDANCE in checker_invoke.call_args.kwargs['prompt']
        assert 'arxiv:2403.01444v4' in checker_invoke.call_args.kwargs['prompt']


def test_generic_input_intent_finds_an_owned_operation_without_both_paper_names():
    selected=[passage(i,'PaperOne and PaperTwo have good results.',section='Introduction') for i in range(5)]
    own=passage(20,'The input to our method is images of a monocular dynamic scene with camera poses.',section='Method')
    foreign=passage(21,own['text'],owner='foreign',section='Method')
    other_version=passage(22,own['text'],version='b'*16,section='Method')
    query='PaperOne input data PaperTwo input data'
    assert include_method_details(selected,[own,foreign,other_version],query,'p',5)==selected
    found=include_method_details(selected,[own,foreign,other_version],query,'p',5,semantic_intent=True)
    assert found[0]==selected[0] and found[1]['sourceId']==own['sourceId'] and len(found)==5
    assert found[1]['text']==own['text']


def test_generic_temporal_intent_keeps_explicit_state_transfer_with_exact_prior_context():
    selected=[passage(i,'General implementation details.',section='Implementation') for i in range(5)]
    previous=passage(20,'We map positions through the transformation network.',section='Transform')
    detail=passage(21,'This transforms the previous frame position and rotation, and passes them to the next frame.',section='Transform')
    found=include_method_details(selected,[previous,detail],'PaperOne temporal representation PaperTwo temporal representation','p',5,semantic_intent=True)
    assert [r['sourceId'] for r in found[:3]]==[selected[0]['sourceId'],previous['sourceId'],detail['sourceId']]
    assert found[1]['contextForSourceId']==detail['sourceId']


def test_extraction_input_priority_preserves_both_papers_instead_of_name_overlap():
    pending=[]
    for paper in ['a','b']:
        for section,text in [('Introduction','PaperOne input data PaperTwo input data'),
                             ('Method','The input to our method is monocular video images with calibrated camera poses.')]:
            pending.append(({'sourceId':paper+section,'workId':paper,'obligationIds':['o']},{'section':section},text))
    before=deepcopy(pending)
    obligations={'o':{'obligationId':'o','question':'它们分别使用什么输入','searchQuery':'PaperOne input data PaperTwo input data','requiredSources':['a','b']}}
    found=prioritize_extraction_passages(pending,obligations,5)
    assert [r[0]['sourceId'] for r in found[:2]]==['aMethod','bMethod'] and pending==before
    assert set(r[0]['sourceId'] for r in found)==set(r[0]['sourceId'] for r in pending)
