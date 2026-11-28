import pytest
from types import SimpleNamespace

from services.deep_research.named_benchmark_navigation import include_named_benchmark_tables, preferred_benchmark_reads


VERSION = 'a' * 16
QUESTION = '核对 PaperScore 和 NewsEval 的报告数值与版本差异。'
QUERY = 'check PaperScore and NewsEval benchmark results'


def row(i, values=(), *, owner='p', index_version=VERSION):
    packet_rows = [[n, 'Method', [f'{52+n}.0', f'{67+n}.0']] for n in values]
    text = '\n'.join(f'Table row {n}: ' + ' | '.join([method, *cells]) for n, method, cells in packet_rows)
    return {'sourceId':f'{owner}-v{index_version}-chunk-{i}', 'pdfId':owner, 'sourceType':'current_paper',
            'accessLevel':'fulltext', 'text':text or 'A paper overview with no benchmark results.',
            'location':{'chunk':i,'section':'Table 1','table':'t1'},
            'metadata':{'id':owner,'index_version':index_version,'section_title':'Table 1','chunk_index':i},
            **({'tableData':{'groups':[['PaperScore',['Accuracy']],['NewsEval',['F1']]],'rows':packet_rows}}
               if packet_rows else {})}


def record(*, human=QUESTION, query=QUERY):
    obligation = {'obligationId':'o','question':QUESTION,'searchQuery':query,'requiredSources':['p']}
    return {'question':human,'state':{'plan':[{'obligations':[obligation]}]}}, obligation


def test_named_verified_chunks_fit_the_existing_budget_without_repeating_rows():
    entry, _ = record()
    sources = [row(i) for i in range(1,4)]
    first, overlap, second = row(4, [2,3]), row(5, [2,3]), row(6, [6])
    result = include_named_benchmark_tables(sources,[*sources,first,overlap,second],entry,QUERY,'p',3)
    assert result == [sources[0],first,second]


def test_local_retrieval_uses_named_benchmark_navigation_only_for_the_new_run_contract():
    from services.deep_research.local_sources import LocalTaskRetriever

    entry, _ = record()
    entry['scopeEvidenceContractVersion'] = 1
    sources = [row(1),row(2)]
    table = row(3,[2,3])
    retriever = LocalTaskRetriever(SimpleNamespace(require_run=lambda _:entry), 'r', lambda *_:True,
                                   origin='http://localhost')
    assert retriever._scope_evidence(sources,[*sources,table],QUERY,'p',2) == sources
    entry['namedBenchmarkNavigationVersion'] = 1
    assert retriever._scope_evidence(sources,[*sources,table],QUERY,'p',2) == [sources[0],table]


@pytest.mark.parametrize('why', ['prefix_only', 'not_human_requested', 'other_owner', 'old_index',
                                'missing_literal_rows', 'duplicate_identity', 'unrelated_obligation'])
def test_unowned_or_unrequested_rows_cannot_fill_the_table_slots(why):
    selected = [row(1),row(2)]
    entry, target = record()
    table = row(3,[2])
    candidates=[table]
    if why == 'prefix_only':
        entry['question']='核对 PaperScorePlus 的报告数值。'
    elif why == 'not_human_requested':
        entry['question']='核对实验的结果。'
    elif why == 'other_owner':
        candidates=[row(3,[2],owner='other')]
    elif why == 'old_index':
        candidates=[row(3,[2],index_version='b'*16)]
    elif why == 'missing_literal_rows':
        table['text']='Table row 2: Method | 99.0 | 69.0'
    elif why == 'duplicate_identity':
        candidates=[table,table]
    else:
        target['searchQuery']='another query'
    assert include_named_benchmark_tables(selected,candidates,entry,QUERY,'p',2) == selected


def test_read_allocation_gives_each_version_a_first_slot_before_any_second_slot():
    _, obligation = record()
    obligation['requiredSources']=['p','q']
    p1,p2,q1 = row(4,[2,3,4]),row(5,[5]),row(7,[2],owner='q')
    for candidate,version in ((p1,'v1'),(p2,'v1'),(q1,'v2')):
        candidate.update(workId=candidate['pdfId'],ownerMaterialId=candidate['pdfId'],versionId=version,
                         obligationIds=['o'],contentHash=candidate['pdfId'])
    assert preferred_benchmark_reads([p1,p2,q1],{'o':obligation},QUESTION,6,set()) == [p1,q1,p2]
    assert preferred_benchmark_reads([p1,p2,q1],{'o':obligation},QUESTION,4,set()) == [p1,q1]
    assert preferred_benchmark_reads([p1,p2,q1],{'o':obligation},QUESTION,4,{(p1['sourceId'],'p')}) == [p2,q1]
