from copy import deepcopy

import pytest

from services.deep_research.revision_table_display import contradictory_revision_values, materialize
from services.deep_research.table_bindings import validate_declared_references, validate_table_bindings


def revision(value, number, digest):
    return {'evidenceId': f'e{number}', 'contentHash': 'chunk-hash', 'sourceWorkId': digest + '.pdf',
            'sourceVersionId': digest, 'ownerMaterialId': digest + '.pdf', 'accessLevel': 'fulltext',
            'verification': {'literal': 'passed'}, 'location': {'table': 'pdf-page-3-table-1', 'section': 'Table 1'},
            'sourcePublicationIdentity': {'scheme':'arxiv','workId':'arxiv:2306.00978', 'revision':f'v{number}',
                'displayId':f'arxiv:2306.00978v{number}', 'contentHash':digest, 'physicalPage':1,
                'literalStamp':f'arXiv:2306.00978v{number}', 'origin':'owned_pdf_header'},
            'quote': f'Table row 2: OPT-1.3B | {value}',
            'tableData': {'groups': [['Activation', ['1%']]], 'rows': [[2, 'OPT-1.3B', [value]]]}}


@pytest.mark.parametrize('fault', [None, 'wrong_hash', 'uncited', 'invalid_cell', 'different_row', 'wrong_table'])
def test_cross_revision_results_use_verified_owners_and_exact_cells(fault):
    old = revision('18.51', 1, 'a' * 64)
    new = revision('16.91', 2, 'b' * 64)
    claim = {'claimId':'answer','kind':'reported','text':'v1 16.91，v2 18.51。','evidenceRefs':['e2','e1'],
             'obligationIds':['o1','o2'],'tableBindings':[
                 {'evidenceId':'e2','sourceRowNumber':2,'groupIndex':0,'metricKey':'1%','value':'16.91'},
                 {'evidenceId':'e1','rowNumber':2,'groupIndex':0,'metric':'1%','value':'18.51'},
             ]}
    if fault == 'wrong_hash':
        new['sourcePublicationIdentity']['contentHash'] = old['sourceVersionId']
    elif fault == 'uncited':
        claim['evidenceRefs'] = ['e1']
    elif fault == 'invalid_cell':
        claim['tableBindings'][0]['value'] = '18.51'
    elif fault == 'different_row':
        new['tableData']['rows'][0][1] = 'OPT-6.7B'
        new['quote'] = new['quote'].replace('OPT-1.3B', 'OPT-6.7B')
    elif fault == 'wrong_table':
        new['location'].update(table='pdf-page-3-table-2', section='Table 2')

    report = {'claims':[claim]}
    saved = deepcopy(report)
    compiled, fixed = materialize(report, [old,new], '1')
    assert report == saved
    if fault:
        assert compiled == report and not fixed
    else:
        rendered, = compiled['claims']
        assert rendered['text'] == '表 1 OPT-1.3B（Activation · 1%）依次为 v1 18.51，v2 16.91。'
        assert rendered['evidenceRefs'] == claim['evidenceRefs'] and rendered['obligationIds'] == claim['obligationIds']
        assert fixed == ['answer'] and validate_declared_references(rendered, [old,new]) is None
        assert validate_table_bindings(rendered, [old,new]) is None
        assert not contradictory_revision_values(rendered, [old,new], '1')


def test_inference_cannot_repeat_the_other_versions_known_table_value_as_an_operand():
    from services.deep_research.verification import precheck_claims

    sources = [revision('18.51', 1, 'a' * 64), revision('16.91', 2, 'b' * 64)]
    claim = {'claimId':'summary','kind':'inference','text':'OPT-1.3B（v1: 16.91，v2: 18.51）。',
             'evidenceRefs':['e1','e2']}
    rejection, = precheck_claims([claim], sources, named_revision_table='1')['rejected']
    assert rejection['reason'] == 'table_revision_value_mismatch'
    assert not contradictory_revision_values(claim, sources, '2')
    assert not contradictory_revision_values({**claim, 'text':'OPT-1.3B（v1: 18.51，v2: 16.91）。'}, sources, '1')


def test_multiple_rows_keep_each_versions_values_and_require_matching_coordinates():
    sources = [revision('18.51', 1, 'a' * 64), revision('16.91', 2, 'b' * 64)]
    bindings = []
    for source, value in zip(sources, ('13.02', '11.39'), strict=True):
        source['tableData']['rows'].append([3, 'OPT-6.7B', [value]])
        source['quote'] += f'\nTable row 3: OPT-6.7B | {value}'
        for row, _, (measurement,) in source['tableData']['rows']:
            bindings.append({'evidenceId': source['evidenceId'], 'rowNumber': row,
                             'groupIndex': 0, 'metric': '1%', 'value': measurement})
    claim = {'claimId': 'result', 'kind': 'reported', 'text': 'Original prose',
             'evidenceRefs': ['e1', 'e2'], 'obligationIds': ['o1', 'o2'], 'tableBindings': bindings}
    report = {'claims': [claim]}
    assert materialize(report, sources, '1') == (report, [])
    compiled, fixed = materialize(report, sources, '1', multiple_rows=True)
    rendered, = compiled['claims']
    assert fixed == ['result']
    assert rendered['text'] == '表 1（Activation · 1%）OPT-1.3B 为 v1 18.51，v2 16.91；OPT-6.7B 为 v1 13.02，v2 11.39。'
    assert rendered['tableBindings'] == bindings and rendered['obligationIds'] == ['o1', 'o2']
    assert validate_table_bindings(rendered, sources) is None
    assert not contradictory_revision_values(rendered, sources, '1')
    incomplete = {'claims': [{**claim, 'tableBindings': bindings[:-1]}]}
    assert materialize(incomplete, sources, '1', multiple_rows=True) == (incomplete, [])


def test_invalid_sibling_does_not_block_exact_revision_cells():
    sources = [revision('18.51', 1, 'a' * 64), revision('16.91', 2, 'b' * 64)]
    bindings = [{'evidenceId': row['evidenceId'], 'rowNumber': 2, 'groupIndex': 0,
                 'metric': '1%', 'value': value}
                for row, value in zip(sources, ('18.51', '16.91'), strict=True)]
    claim = {'claimId': 'cells', 'kind': 'reported', 'text': 'Draft', 'evidenceRefs': ['e1', 'e2'],
             'tableBindings': bindings}
    sibling = {**claim, 'claimId': 'blocked'}
    body, fixed = materialize({'claims': [claim, sibling]}, sources, '1',
                              excluded_claim_ids={'blocked'})
    assert fixed == ['cells'] and body['claims'][1] == sibling
    assert validate_table_bindings(body['claims'][0], sources) is None


def test_single_version_display_adds_only_its_verified_original_groups():
    from services.deep_research.table_bindings import validate_table_bindings

    source = revision('18.51', 1, 'a' * 64)
    source['tableData']['rows'].append([3, 'OPT-6.7B', ['13.02']])
    source['quote'] += '\nTable row 3: OPT-6.7B | 13.02'
    claim = {'claimId':'v1','kind':'reported','text':'v1 的 OPT-1.3B 为 18.51，OPT-6.7B 为 13.02。',
             'evidenceRefs':['e1'],'tableBindings':[
        {'evidenceId':'e1','rowNumber':n,'groupIndex':0,'metric':'1%','value':value}
        for n,value in ((2,'18.51'),(3,'13.02'))]}
    report={'claims':[claim]}
    assert materialize(report,[source],'1',multiple_rows=True) == (report,[])
    rendered, fixed = materialize(report,[source],'1',multiple_rows=True,single_revision_display=True)
    assert fixed==['v1']
    assert rendered['claims'][0] == {**claim,'text':claim['text']+'（原表列 Activation · 1%）'}
    assert validate_table_bindings(rendered['claims'][0],[source]) is None
    assert materialize(rendered,[source],'1',multiple_rows=True,single_revision_display=True) == (rendered,[])


def test_changed_tables_print_shared_rows_and_each_revisions_distinct_rows():
    old, new = revision('18.51', 1, 'a' * 64), revision('18.51', 2, 'b' * 64)
    added = 'OPT-1.3B / 4bit (K -T, V -T)'
    new['tableData']['rows'].append([3, added, ['16.44']])
    new['quote'] += f'\nTable row 3: {added} | 16.44'
    bindings = [{'evidenceId':row['evidenceId'], 'rowNumber':n,'groupIndex':0,'metric':'1%','value':values[0]}
                for row in (old,new) for n,_,values in row['tableData']['rows']]
    claim = {'claimId':'values','kind':'reported','text':'Draft','evidenceRefs':['e1','e2'],'tableBindings':bindings}
    report={'claims':[claim]}
    assert materialize(report,[old,new],'1',multiple_rows=True) == (report,[])
    body,fixed=materialize(report,[old,new],'1',multiple_rows=True,differing_revision_rows=True)
    assert fixed==['values']
    changed,=body['claims']
    assert changed['text']==f'表 1（Activation · 1%）OPT-1.3B 为 v1、v2 18.51；{added} 为 v2 16.44。'
    assert changed['tableBindings']==bindings
    assert validate_table_bindings(changed,[old,new]) is None

    broken = deepcopy(report)
    broken['claims'][0]['tableBindings'][-1]['value']='16.45'
    assert materialize(broken,[old,new],'1',multiple_rows=True,differing_revision_rows=True)==(broken,[])


@pytest.mark.parametrize('new_values, question, new_metric, ordered', [
    (['15', '100', '17'], '核对 1% 的表项，并说明两版共同支持的结论。', 'perplexity', True),
    (['15', '100', '14'], '核对 1% 的表项，并说明两版共同支持的结论。', 'perplexity', False),
    (['15', '100', '15'], '核对 1% 的表项，并说明两版共同支持的结论。', 'perplexity', False),
    (['15', '100', '17'], '核对 0.1% 的表项，并说明两版共同支持的结论。', 'perplexity', False),
    (['15', '100', '17'], '仅列出两版表项的数值。', 'perplexity', False),
    (['15', '100', '17'], '核对 1% 的表项，并说明两版共同支持的结论。', 'accuracy', False),
])
def test_shared_order_comes_only_from_matching_verified_settings(new_values, question, new_metric, ordered):
    sources = [revision('20', 1, 'a' * 64), revision('17', 2, 'b' * 64)]
    groups = [['', ['FP16', 'RTN']], ['FP16% Activation', ['1%']]]
    bindings = []
    for row, values, metric_name in zip(sources, (['16', '200', '20'], new_values), ('perplexity', new_metric), strict=True):
        row['tableData'] = {'groups': groups, 'rows': [[2, 'OPT-1.3B', values]]}
        row['quote'] = f'We measured {metric_name}.\nTable row 2: OPT-1.3B | ' + ' | '.join(values)
        bindings.extend({'evidenceId':row['evidenceId'], 'rowNumber':2, 'groupIndex':group,
                         'metric':metric, 'value':value}
                        for (group, metric), value in zip(((0, 'FP16'), (0, 'RTN'), (1, '1%')), values, strict=True))
    claim = {'claimId':'values','kind':'reported','text':'Draft','evidenceRefs':['e1','e2'],'tableBindings':bindings}
    result, fixed = materialize({'claims':[claim]}, sources, '1', shared_findings_question=question)
    rendered, = result['claims']
    assert fixed == ['values'] and rendered['tableBindings'] == bindings
    assert ('各版所列模型的数值均从低到高为 FP16、FP16% Activation · 1%、RTN。' in rendered['text']) is ordered
    assert validate_table_bindings(rendered, sources) is None


def test_reported_metric_name_resolves_only_a_unique_value_in_the_verified_row():
    sources = [revision('18.51', 1, 'a' * 64), revision('16.91', 2, 'b' * 64)]
    bindings = []
    for row, value in zip(sources, ('18.51', '16.91'), strict=True):
        row['quote'] = 'We measured the WikiText perplexity ( ↓ ).\n' + row['quote']
        bindings.append({'evidenceId': row['evidenceId'], 'rowNumber': 2, 'groupIndex': 0,
                         'metric': 'WikiText perplexity (↓)', 'value': value})
    claim = {'claimId': 'cells', 'kind': 'reported', 'text': 'Draft', 'evidenceRefs': ['e1', 'e2'],
             'tableBindings': bindings}
    report = {'claims': [claim]}
    assert materialize(report, sources, '1', reconcile_coordinates=True) == (report, [])
    body, fixed = materialize(report, sources, '1', reconcile_coordinates=True, measured_metric_alias=True)
    assert fixed == ['cells']
    assert validate_table_bindings(body['claims'][0], sources) is None
    sources[0]['tableData']['groups'][0][1].append('2%')
    sources[0]['tableData']['rows'][0][2].append('18.51')
    sources[0]['quote'] += ' | 18.51'
    assert materialize(report, sources, '1', reconcile_coordinates=True,
                       measured_metric_alias=True) == (report, [])
    sources[1]['tableData']['groups'][0][1].append('2%')
    sources[1]['tableData']['rows'][0][2].append('16.91')
    sources[1]['quote'] += ' | 16.91'
    for row, value in zip(sources, ('13.02', '11.39'), strict=True):
        row['tableData']['rows'].append([3, 'OPT-6.7B', [value, '25.00']])
        row['quote'] += f'\nTable row 3: OPT-6.7B | {value} | 25.00'
        bindings.append({'evidenceId': row['evidenceId'], 'rowNumber': 3, 'groupIndex': 0,
                         'metric': 'WikiText perplexity (↓)', 'value': value})
    body, fixed = materialize(report, sources, '1', multiple_rows=True, reconcile_coordinates=True,
                              measured_metric_alias=True)
    assert fixed == ['cells'] and validate_table_bindings(body['claims'][0], sources) is None
    bindings.pop()  # The other revision's column cannot resolve the duplicate here.
    assert materialize(report, sources, '1', multiple_rows=True, reconcile_coordinates=True,
                       measured_metric_alias=True) == (report, [])


def test_flat_column_reference_reconciles_only_a_unique_exact_cell():
    sources = [revision('18.51', 1, 'a' * 64), revision('16.91', 2, 'b' * 64)]
    bindings = [{'evidenceId': source['evidenceId'], 'rowNumber': 2, 'groupIndex': 4,
                 'metric': 'Activation / 1%', 'value': value}
                for source, value in zip(sources, ('18.51', '16.91'), strict=True)]
    report = {'claims': [{'claimId':'measurement','kind':'reported','text':'v1 16.91，v2 18.51。',
                          'evidenceRefs':['e1','e2'],'tableBindings':bindings}]}
    assert materialize(report, sources, '1') == (report, [])
    compiled, fixed = materialize(report, sources, '1', reconcile_coordinates=True)
    assert fixed == ['measurement']
    claim, = compiled['claims']
    assert claim['text'] == '表 1 OPT-1.3B（Activation · 1%）依次为 v1 18.51，v2 16.91。'
    assert validate_declared_references(claim, sources) is None
    for source in sources:
        source['tableData']['groups'].append(['Other', ['1%']])
        source['tableData']['rows'][0][2].append(source['tableData']['rows'][0][2][0])
        source['quote'] += ' | ' + source['tableData']['rows'][0][2][0]
    ambiguous = deepcopy(report)
    for binding in ambiguous['claims'][0]['tableBindings']:
        binding['metric'] = '1%'
    assert materialize(ambiguous, sources, '1', reconcile_coordinates=True) == (ambiguous, [])
