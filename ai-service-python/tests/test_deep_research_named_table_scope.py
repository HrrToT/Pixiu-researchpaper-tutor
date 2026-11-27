from services.deep_research.named_table_scope import include_indexed_rows, prioritize, requested_number, requested_row_numbers, select
from services.deep_research.request_context import ResearchQuestion


def evidence(eid, *, version='v1', page=7, section='', quote='Results fragment.', table=None):
    return {'evidenceId': eid, 'sourceWorkId': 'work', 'sourceVersionId': version, 'ownerMaterialId': 'work',
            'accessLevel': 'fulltext', 'verification': {'literal': 'passed'}, 'quote': quote,
            'location': {'page': page, 'pageResolution': 'exact', 'section': section, 'table': table}}


def test_requested_table_looks_only_at_current_human_instructions():
    assert requested_number('核对两篇表 3；同一项见 Table 3。') == '3'
    assert requested_number('比较 Table 3 and 4。') is None
    assert requested_number('比较表 1 与表 3。') is None
    followup = ResearchQuestion('解释影响。此前讨论表3。', ['解释影响。', '此前讨论表3。'], ['解释影响。'])
    assert requested_number(followup) is None


def test_named_table_filters_other_tables_and_keeps_physical_page_revision_identity():
    wrong = evidence('wrong', page=3, section='Table 1 :', quote='See Table 3.\nTable row 1: Wrong result.')
    caption = evidence('caption', quote='Table 3: Actual results. Similar to Table 1.')
    rows = evidence('rows', quote='Model baseline 2.21')
    different_revision = evidence('different-revision', version='v2')
    unrelated = evidence('unrelated', page=8)
    before = [wrong, caption, rows, different_revision, unrelated]
    retained, matched = select(before, '3')
    assert retained == before[1:]
    assert matched == {'caption', 'rows'}


def test_page_hint_is_ambiguous_with_two_captions_and_table_ids_stay_revision_local():
    caption = evidence('caption', quote='Table 3: Actual results.', table='tab_2')
    same_page = evidence('same-page', quote='Table 4: Ablation.')
    rows = evidence('rows', table='tab_2')
    unrelated = evidence('unrelated')
    reused_table = evidence('reused-table', version='v2', table='tab_2')
    retained, matched = select([caption, same_page, rows, unrelated, reused_table], '3')
    assert retained == [caption, rows, unrelated, reused_table]
    assert matched == {'caption', 'rows'}


def test_retrieval_preserves_two_requested_rows_from_only_the_same_named_table_and_index():
    version = 'a' * 16

    def source(chunk, label, value, *, section='Table 1', table='tab_1', index=version, owner='paper.pdf'):
        return {'sourceId': f'{owner}-v{index}-chunk-{chunk}', 'accessLevel': 'fulltext', 'pdfId': owner,
                'metadata': {'id':owner, 'index_version':index, 'chunk_index':chunk, 'section_title':section},
                'location': {'section':section, 'chunk':chunk, 'table':table},
                'text': f'Table row {chunk}: {label} | {value}',
                'tableData': {'groups': [['', ['Loss']]], 'rows': [[chunk, label, [value]]]}}

    first = source(2, 'OPT-1.3B', '18.51')
    second = source(3, 'OPT-6.7B', '13.02')
    generic = {**source(4, 'Unasked', '107.1'), 'tableData': None}
    wrong = source(5, 'OPT-6.7B', '17.00', section='Table 2', table='tab_2')
    stale = source(6, 'OPT-6.7B', '21.15', index='b' * 16)
    foreign = source(7, 'OPT-6.7B', '42.00', owner='other.pdf')
    request = {'question': '核对表 1 中 OPT-1.3B 和 OPT-6.7B 的数值。', 'namedTableScopeVersion': 2,
               'state': {'outputKind': 'claim_verification'}}
    assert include_indexed_rows([first,generic], [wrong,stale,foreign,first,second], request, 'paper.pdf', 2) == [first,second]
    packet_evidence = [evidence(row['sourceId'], section=row['location']['section'], table=row['location']['table'],
                               quote=row['text']) | {'tableData':row['tableData'], 'obligationIds':['o']}
                       for row in (first, second)]
    _, bundles = prioritize(packet_evidence, [], {row['evidenceId'] for row in packet_evidence},
                            request['question'], requested_rows=True)
    assert bundles[0]['evidenceIds'] == [first['sourceId'], second['sourceId']]


def test_required_table_bundle_prioritizes_both_revisions_before_optional_rows():
    rows = []
    for version, value in (('v1', '18.51'), ('v2', '16.91')):
        row = evidence(version, section='Table 1', table='tab_1', version=version,
                       quote=f'Table row 2: OPT-1.3B | {value}')
        row.update(tableData={'groups': [['', ['Loss']]], 'rows': [[2, 'OPT-1.3B', [value]]]},
                   obligationIds=['o'])
        rows.append(row)
    _, bundles = prioritize(rows, [], {'v1','v2'}, '核对表 1 的 OPT-1.3B。',
                            requested_rows=True, keep_revisions_together=True)
    assert bundles[0]['evidenceIds'] == ['v1','v2']
    assert [bundle['evidenceIds'] for bundle in bundles[1:]] == [['v1'],['v2']]


def test_named_table_bundle_retains_each_versions_own_same_page_prose_before_fitting():
    def owned(eid, version, digest, **kwargs):
        owner = digest + '.pdf'
        return {**evidence(eid, version=digest, **kwargs), 'sourceWorkId': owner, 'ownerMaterialId': owner,
                'sourcePublicationIdentity': {'scheme': 'arxiv', 'workId': 'arxiv:2401.12345', 'revision': f'v{version}',
                    'displayId': f'arxiv:2401.12345v{version}', 'contentHash': digest, 'physicalPage': 1,
                    'literalStamp': f'arXiv:2401.12345v{version}', 'origin': 'owned_pdf_header'}}

    tables, prose = [], []
    for version, digest, page in [(1, 'a' * 64, 7), (2, 'b' * 64, 9)]:
        table = owned(f'table-{version}', version, digest, page=page, section='Table 3', table='t3',
                      quote='Table row 2: Method-A | 98.0')
        table.update(tableData={'groups': [['', ['Accuracy']]], 'rows': [[2, 'Method-A', ['98.0']]]},
                     obligationIds=['results'])
        tables.append(table)
        prose.extend([owned(f'other-page-{version}', version, digest, page=page+1,
                            quote='Method-A accuracy drops by 2%.'),
                      owned(f'tradeoff-{version}', version, digest, page=page,
                            quote='Method-A throughput increases 5 percent.'),
                      owned(f'text-{version}', version, digest, page=page,
                            quote='The accuracy drops by 0.5%.')])
    kwargs = {'requested_rows': True, 'keep_revisions_together': True, 'same_page_candidates': [*tables, *prose]}
    ordered, bundles = prioritize(tables, [], {'table-1', 'table-2'},
                                  '核对表3 Method-A 的准确率，并比较同页正文的准确率降幅。', **kwargs)
    assert [row['evidenceId'] for row in ordered] == ['table-1','table-2','text-1','text-2']
    assert bundles[0]['evidenceIds'] == ['table-1','text-1','table-2','text-2']
    unchanged, _ = prioritize(tables, [], {'table-1','table-2'}, '核对表3 Method-A 的准确率。', **kwargs)
    assert unchanged == tables


def test_named_model_group_retains_configurations_and_respects_explicit_size_lists():
    packet = {'rows': [[2,'Llama-2-7B / KIVI-2',['8']], [3,'Llama-2-13B / 16bit',['9']],
                       [4,'Llama-2-13B / KIVI-2',['7']], [5,'Llama-2-70B / FP16',['6']],
                       [6,'Llama-3-70B / FP16',['5']]]}
    question = '核对表 3 的 Llama‑2 13B 和 70B 结果。'
    assert not requested_row_numbers(packet,question)
    assert requested_row_numbers(packet,question,grouped_rows=True)=={3,4,5}
    assert requested_row_numbers({'rows':[[5,'LLAMA2-70B / FP16',['6']]]},question,grouped_rows=True)=={5}
    assert requested_row_numbers(packet,'核对 Llama-2-13B。背景讨论过 70B。',grouped_rows=True)=={3,4}
    followup = ResearchQuestion(question, ['核对 Llama-2-13B。', question], ['核对 Llama-2-13B。'])
    assert requested_row_numbers(packet,followup,grouped_rows=True)=={3,4}
