from services.deep_research.named_table_scope import requested_number, select
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
