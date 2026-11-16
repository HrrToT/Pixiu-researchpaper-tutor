from copy import deepcopy

import pytest

from services.deep_research.comparison_cells import plan_cells, compile_cells


def fixture():
    requirements = [{'obligationId': 'mechanism', 'question': '比较两篇论文的机制',
                     'requiredSourceAliases': ['P1', 'P2']}]
    sources = {'P1': {'title': 'Paper A', 'sourceVersionId': 'a-v1'},
               'P2': {'title': 'Paper B', 'sourceVersionId': 'b-v1'}}
    evidence = [{'evidenceId': 'E1', 'source': 'P1', 'obligations': ['mechanism'],
                 'quote': 'Method A prunes redundant primitives.'},
                {'evidenceId': 'E2', 'source': 'P2', 'obligations': ['mechanism'],
                 'quote': 'Method B quantizes attributes.'}]
    plan = plan_cells(requirements, sources, evidence)
    def point(text, ref):
        return {'kind': 'reported', 'body': {'prose': {'text': text, 'conditions': {}}},
                'evidenceRefs': [ref], 'tableBindings': [], 'detailLevel': 'fulltext'}
    payload = {'cells': [
        {'cellId': 'cell_0_0', 'claims': [point('方法 A 剪除冗余基元。', 'E1')], 'unresolved': False},
        {'cellId': 'cell_0_1', 'claims': [point('方法 B 量化属性。', 'E2')], 'unresolved': False}],
        'conclusions': []}
    return requirements, sources, evidence, plan, payload


def test_shared_axes_align_exact_user_excerpts_without_merging_scientific_obligations():
    req, sources, ev, _, payload = fixture()
    req = [{'obligationId': 'a-mech', 'question': 'Paper A method', 'requestExcerpt': '比较机制',
            'requiredSourceAliases': ['P1']},
           {'obligationId': 'b-mech', 'question': 'Paper B method', 'requestExcerpt': '比较机制',
            'requiredSourceAliases': ['P2']}]
    before = deepcopy((req, sources, ev))
    plan = plan_cells(req, sources, ev, shared_axes=True, question='请比较机制，并说明代价。')
    assert plan['version'] == 2
    assert plan['cells'][0]['axisId'] == plan['cells'][1]['axisId']
    assert all(c['axisTitle'] == '比较机制' for c in plan['cells'])
    payload['cells'][1]['cellId'] = 'cell_1_1'
    result = compile_cells(payload, plan, max_claims=4)
    assert result['layoutVersion'] == 2
    assert [c['obligationIds'] for c in result['report']['claims']] == [['a-mech'], ['b-mech']]
    assert [c['evidenceRefs'] for c in result['report']['claims']] == [['E1'], ['E2']]
    assert before == (req, sources, ev)
    payload['cells'][0]['claims'][0]['evidenceRefs'] = ['E2']
    result = compile_cells(payload, plan, max_claims=4)
    assert len(result['report']['claims']) == 1 and result['errors']


@pytest.mark.parametrize('excerpt', [None, '', 'not present in the user question'])
def test_missing_or_unbound_excerpt_does_not_guess_shared_axes(excerpt):
    _, sources, ev, _, _ = fixture()
    req = [{'obligationId': 'a', 'question': 'Identical generated question', 'requestExcerpt': excerpt},
           {'obligationId': 'b', 'question': 'Identical generated question', 'requestExcerpt': excerpt}]
    result = plan_cells(req, sources, ev, shared_axes=True, question='比较机制')
    assert result['cells'][0]['axisId'] != result['cells'][2]['axisId']
    legacy = plan_cells(req, sources, ev)
    assert legacy['version'] == 1 and all('axisId' not in cell for cell in legacy['cells'])


def test_source_dimension_plan_and_compile_preserve_data_without_scientific_approval():
    req, sources, ev, plan, payload = fixture()
    before = deepcopy((req, sources, ev, plan, payload))
    result = compile_cells(payload, plan, max_claims=4)
    assert [c['sourceTitle'] for c in result['layout']] == ['Paper A', 'Paper B']
    assert [c['evidenceRefs'] for c in result['report']['claims']] == [['E1'], ['E2']]
    assert all(c['obligationIds'] == ['mechanism'] for c in result['report']['claims'])
    assert all('verification' not in c for c in result['report']['claims'])
    assert result['verification'] == 'unchecked' and not result['errors']
    assert before == (req, sources, ev, plan, payload)


@pytest.mark.parametrize('mode', ['foreign', 'internal_label', 'invented_approval', 'bad_body', 'experiment'])
def test_bad_point_is_isolated_while_other_paper_remains_available_for_verification(mode):
    _, _, _, plan, payload = fixture()
    point = payload['cells'][0]['claims'][0]
    if mode == 'foreign': point['evidenceRefs'] = ['E2']
    if mode == 'internal_label': point['body']['prose']['text'] = 'P1 使用剪枝。'
    if mode == 'invented_approval': point['verification'] = {'status': 'passed'}
    if mode == 'bad_body': point['body'] = {'prose': {}, 'boundary': {}}
    if mode == 'experiment': point['kind'] = 'hypothesis'
    result = compile_cells(payload, plan, max_claims=4)
    assert len(result['errors']) == 1
    assert [c['evidenceRefs'] for c in result['report']['claims']] == [['E2']]
    assert result['unresolvedObligationIds'] == ['mechanism']
    assert result['layout'][0]['unresolved'] and not result['layout'][0]['claimIds']


def test_missing_or_explicitly_unresolved_cells_do_not_disappear_from_frozen_scope():
    _, _, _, plan, payload = fixture()
    payload['cells'].pop()
    result = compile_cells(payload, plan, max_claims=4)
    assert len(result['layout']) == 2 and result['layout'][1]['unresolved']
    assert result['unresolvedObligationIds'] == ['mechanism']
    payload['cells'][0].update(claims=[], unresolved=True)
    result = compile_cells(payload, plan, max_claims=4)
    assert not result['report']['claims'] and result['unresolvedObligationIds'] == ['mechanism']


@pytest.mark.parametrize('mode', ['duplicate', 'unknown'])
def test_ambiguous_cell_identity_rejects_the_container(mode):
    _, _, _, plan, payload = fixture()
    if mode == 'duplicate': payload['cells'].append(deepcopy(payload['cells'][0]))
    else: payload['cells'][0]['cellId'] = 'not_in_plan'
    with pytest.raises(ValueError, match='identity'): compile_cells(payload, plan, max_claims=4)


def test_empty_required_source_mapping_keeps_an_unresolved_obligation():
    req, sources, ev, _, _ = fixture(); req[0]['requiredSourceAliases'] = []
    plan = plan_cells(req, sources, ev)
    result = compile_cells({'cells': [], 'conclusions': []}, plan, max_claims=4)
    assert not plan['cells'] and result['unresolvedObligationIds'] == ['mechanism']


def test_claim_limit_is_not_increased_to_fit_the_matrix():
    _, _, _, plan, payload = fixture()
    with pytest.raises(ValueError, match='budget'): compile_cells(payload, plan, max_claims=1)


def test_a_real_source_symbol_remains_subject_to_existing_semantic_checks():
    req, sources, ev, _, payload = fixture(); ev[0]['quote'] = 'E1 denotes energy.'
    plan = plan_cells(req, sources, ev)
    payload['cells'][0]['claims'][0]['body']['prose']['text'] = 'E1 表示能量。'
    result = compile_cells(payload, plan, max_claims=4)
    assert len(result['report']['claims']) == 2


def test_compiled_wrong_number_still_fails_the_existing_verifier():
    from services.deep_research.draft_validation import materialize_claims
    from services.deep_research.verification import precheck_claims
    _, _, _, plan, payload = fixture()
    payload['cells'][0]['claims'][0]['body']['prose']['text'] = '结果为 99.0 dB。'
    compiled = compile_cells(payload, plan, max_claims=4)
    report, _, _ = materialize_claims(compiled['report'], 5, authored_body=True)
    ev = [{'evidenceId': 'E1', 'quote': 'The result is 31.25 dB.',
           'sourceWorkId': 'a', 'sourceVersionId': 'v1', 'accessLevel': 'fulltext',
           'verification': {'literal': 'passed', 'semantic': 'unchecked'}}]
    result = precheck_claims(report['claims'][:1], ev)
    assert result['rejected'][0]['reason'] == 'numeric_mismatch'


def test_extraction_origin_tags_are_navigation_not_cross_goal_reuse_permissions():
    req,sources,ev,_,_=fixture()
    req.append({'obligationId':'choice','question':'给出有条件的选择建议',
                'requiredSourceAliases':['P1','P2']})
    plan=plan_cells(req,sources,ev)
    choice=[c for c in plan['cells'] if c['obligationId']=='choice']
    assert [c['evidenceIds'] for c in choice]==[['E1'],['E2']]
    assert all(c['preferredEvidenceIds']==[] for c in choice)


def test_conclusions_bind_only_explicit_frozen_goals_and_remain_unverified():
    req,sources,ev,_,payload=fixture()
    req.append({'obligationId':'choice','question':'如何选择','requiredSourceAliases':['P1','P2']})
    plan=plan_cells(req,sources,ev)
    point={'kind':'proposal','body':{'prose':{'text':'建议核对目标设备条件后选择。','conditions':{}}},
           'evidenceRefs':['E1','E2']}
    payload['conclusions']=[{'obligationIds':['choice'],'claim':point}]
    result=compile_cells(payload,plan,max_claims=4)
    assert result['report']['claims'][-1]['obligationIds']==['choice']
    assert result['report']['claims'][-1]['kind']=='proposal'
    payload['conclusions'][0]['obligationIds']=['invented_goal']
    result=compile_cells(payload,plan,max_claims=4)
    assert result['errors'][-1]['reason']=='invalid_conclusion_obligations'
    assert len(result['report']['claims'])==2


def test_required_work_or_version_identity_does_not_add_unrequested_papers():
    req,sources,ev,_,_=fixture();req[0].pop('requiredSourceAliases')
    req[0]['requiredSources']=['a-v1']
    plan=plan_cells(req,sources,ev)
    assert [c['source'] for c in plan['cells']]==['P1']
    req[0]['requiredSources']=['unavailable-version']
    plan=plan_cells(req,sources,ev)
    assert plan['cells']==[]
    assert compile_cells({'cells':[],'conclusions':[]},plan,max_claims=4)['unresolvedObligationIds']==['mechanism']
