from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.contracts import DeepResearchError
from services.deep_research.extraction import make_batched_extract_node
from services.deep_research.source_passages import spans, MAX_PASSAGE_BYTES, projection
from services.deep_research.selection import surrounding_context
from services.deep_research.repository import DeepResearchRepository
from services.deep_research.verification import make_evidence
from test_deep_research_extraction import setup
from test_deep_research_adaptive_extraction import activate


def fixture(tmp_path, reads=None):
    repo, old = setup(tmp_path)
    repo = activate(repo, adaptiveExtractionContractVersion=2)
    repo.update_run('r', lambda r:{**r,'state':{**r['state'],'evidence':[]}})
    if reads is not None:
        repo.update_run('r', lambda r:{**r,'state':{**r['state'],'readResults':reads}})
    invoke = Mock(side_effect=AssertionError('No model transcription allowed'))
    return repo, invoke, old


def node(repo, invoke, scope=lambda *_:True):
    return make_batched_extract_node(invoke, make_evidence, scope, repo.update_run)


def test_raw_passages_keep_all_sources_and_are_not_semantically_approved(tmp_path):
    repo, invoke, reads = fixture(tmp_path)
    before = deepcopy(repo.require_run('r')['budget'])
    result = node(repo,invoke)({'run_id':'r'})
    saved=repo.require_run('r'); evidence=saved['state']['evidence']
    assert len(evidence)==3 and result['extraction_pending'] is False
    for e,source in zip(evidence,reads):
        assert e['quote']==e['sourceContext']==source['pages'][0]['text']
        assert e['conditions']=={} and e['verification']=={'literal':'passed','semantic':'unchecked'}
        assert (e['sourceWorkId'],e['sourceVersionId'],e['contentHash'])==(source['workId'],source['versionId'],source['contentHash'])
    invoke.assert_not_called(); assert saved['budget']==before
    assert not repo.list_calls('r')


@pytest.mark.parametrize('text',['中文原文。'*1700,'A complete clause. '*900,'x'*10001,'🦊'*1200],ids=['chinese','english','longword','emoji'])
def test_partition_keeps_every_character_and_never_splits_utf8_characters(text):
    ranges=list(spans(text)); pieces=[text[a:b] for a,b in ranges]
    assert ''.join(pieces)==text
    assert all(0<len(p.encode('utf8'))<=MAX_PASSAGE_BYTES for p in pieces)
    assert ranges[0][0]==0 and ranges[-1][1]==len(text)
    assert all(a[1]==b[0] for a,b in zip(ranges,ranges[1:]))


def test_sentence_groups_preserve_decimal_values_and_pdf_line_wraps():
    text='First value is 3.14 and its\nline wraps. Second rule. Third rule. Fourth rule.'
    pieces=[text[a:b] for a,b in spans(text)]
    assert pieces==['First value is 3.14 and its\nline wraps. Second rule. Third rule.',' Fourth rule.']


def test_index_wrapper_is_metadata_not_quoted_body_or_context(tmp_path):
    repo,invoke,reads=fixture(tmp_path);source=reads[0]
    source.update(title='Exact title',location={'page':3,'section':'Method'},ownerMaterialId='owner',
        publicationIdentity={'revision':'v1'})
    body='The exact operative rule preserves the complete quoted source sentence.'
    prefix='Paper: Exact title\n\nSection: Method\n\nContent:\n'
    source['pages']=[{'text':prefix+body}]
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'readResults':[source]}})
    node(repo,invoke)({'run_id':'r'});e=repo.require_run('r')['state']['evidence'][0]
    assert e['quote']==body and e['sourceContext']==prefix+body
    assert e['location']['sourcePassageStart']==e['sourceQuoteStart']==len(prefix)
    assert e['ownerMaterialId']=='owner' and e['sourcePublicationIdentity']=={'revision':'v1'}
    assert 'Paper:' not in str(surrounding_context(e))


def test_repeated_quote_uses_its_recorded_occurrence_and_rejects_invalid_offsets():
    quote='Identical repeated clause.';source='FIRST '+quote+' MIDDLE '+quote+' LAST'
    e={'quote':quote,'sourceContext':source,'sourceQuoteStart':source.rindex(quote)}
    context=surrounding_context(e)
    assert 'MIDDLE' in context['before'] and context['after'].endswith(' LAST')
    for change in ({'sourceQuoteStart':True},{'sourceQuoteStart':999},{'sourceContextStart':999}):
        assert surrounding_context({**e,**change})=={}


def test_every_long_passage_part_is_saved_without_dropping_tail(tmp_path):
    repo,invoke,reads=fixture(tmp_path);text='Complete sentence about a training operation. '*240
    reads[0]['pages'][0]['text']=text
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'readResults':[reads[0]]}})
    node(repo,invoke)({'run_id':'r'});rows=repo.require_run('r')['state']['evidence']
    assert ''.join(e['quote'] for e in rows)==text and len(rows)>1
    assert all(text[e['sourceQuoteStart']:e['sourceQuoteStart']+len(e['quote'])]==e['quote'] for e in rows)
    assert len({e['evidenceId'] for e in rows})==len(rows)


def test_snapshot_denial_or_late_source_denial_keeps_no_partial_evidence(tmp_path):
    repo,invoke,_=fixture(tmp_path)
    for scope in (lambda *_:False, lambda _,work:work!='p1'):
        with pytest.raises(DeepResearchError,match='范围核对'):node(repo,invoke,scope)({'run_id':'r'})
        assert repo.require_run('r')['state']['evidence']==[]
    class Scope:
        def validate_materials(self,run,works):return False
        def __call__(self,*_):pytest.fail('Use the full snapshot')
    with pytest.raises(DeepResearchError):node(repo,invoke,Scope())({'run_id':'r'})
    invoke.assert_not_called()


def test_resume_reuses_exact_rows_and_detects_journal_or_source_tampering(tmp_path):
    repo,invoke,_=fixture(tmp_path);node(repo,invoke)({'run_id':'r'});old=repo.require_run('r')['state']
    repo=DeepResearchRepository(repo.db_path);repo.initialize()
    node(repo,invoke)({'run_id':'r'});assert repo.require_run('r')['state']==old
    for target in ('quote','sourceQuoteStart','conditions','journal'):
        modified=deepcopy(old)
        if target=='journal':next(iter(modified['sourcePassageExtraction']['entries'].values()))['input']['quote']='forged'
        else:modified['evidence'][0][target]={'changed':True} if target=='conditions' else 'forged'
        repo.update_run('r',lambda r:{**r,'state':modified})
        with pytest.raises(DeepResearchError,match='已改变'):node(repo,invoke)({'run_id':'r'})
    invoke.assert_not_called()


def test_required_source_and_metadata_access_do_not_acquire_permission(tmp_path):
    repo,invoke,reads=fixture(tmp_path)
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'plan':[{'itemId':'i','obligations':[
        {'obligationId':'o','question':'exact material','requiredSources':['p0']}]}]}})
    reads[0]['accessLevel']='metadata'
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'readResults':reads}})
    node(repo,invoke)({'run_id':'r'});assert repo.require_run('r')['state']['evidence']==[]


def test_only_visible_parser_established_table_rows_gain_table_data(tmp_path):
    repo,invoke,reads=fixture(tmp_path)
    source=reads[0];source['tableData']={'groups':[['dataset',['Metric']]], 'rows':[[1,'ours',['3']],[2,'other',['7']]]}
    source['pages']=[{'text':'Table row 1: ours | 3\nA literal description of the table.'}]
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'readResults':[source]}})
    node(repo,invoke)({'run_id':'r'});e=repo.require_run('r')['state']['evidence'][0]
    assert e['tableData']['rows']==[[1,'ours',['3']]]


def test_prose_partition_never_loses_a_parser_established_table_row(tmp_path):
    repo,invoke,reads=fixture(tmp_path)
    source=reads[0];value='3'*3100
    source['tableData']={'groups':[['dataset',['Metric']]],'rows':[[1,'ours',[value]]]}
    row='Table row 1: ours | '+value
    source['pages']=[{'text':'Original preface.\n'+row+'\nOriginal tail.'}]
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'readResults':[source]}})
    node(repo,invoke)({'run_id':'r'})
    evidence=repo.require_run('r')['state']['evidence']
    assert any(e['quote']==row and e.get('tableData',{}).get('rows')==[[1,'ours',[value]]] for e in evidence)


def test_new_goal_merges_obligations_without_changing_source_or_claiming_relevance(tmp_path):
    repo,invoke,_=fixture(tmp_path);node(repo,invoke)({'run_id':'r'})
    original=deepcopy(repo.require_run('r')['state']['evidence'])
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'plan':[{'itemId':'new','obligations':[
        {'obligationId':'new_goal','question':'A different question','requiredSources':['p0']}]}]}})
    node(repo,invoke)({'run_id':'r'});now=repo.require_run('r')['state']['evidence']
    assert len(now)==len(original) and all(projection(a)==projection(b) for a,b in zip(original,now))
    assert now[0]['obligationIds']==['o','new_goal'] and now[1]['obligationIds']==['o']
    assert now[0]['verification']['semantic']=='unchecked'


def test_wrong_wrapper_identity_and_capacity_fail_before_checkpoint(tmp_path,monkeypatch):
    repo,invoke,reads=fixture(tmp_path)
    reads[0].update(title='Real',location={'section':'Method'})
    reads[0]['pages']=[{'text':'Paper: Forged\n\nSection: Method\n\nContent:\nBody.'}]
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'readResults':reads}})
    with pytest.raises(DeepResearchError,match='包装'):node(repo,invoke)({'run_id':'r'})
    reads[0]['pages']=[{'text':'Actual original body.'}]
    repo.update_run('r',lambda r:{**r,'state':{**r['state'],'readResults':reads}})
    monkeypatch.setattr('services.deep_research.source_passages.MAX_UNITS',1)
    with pytest.raises(DeepResearchError,match='上限'):node(repo,invoke)({'run_id':'r'})
    assert repo.require_run('r')['state']['evidence']==[]
