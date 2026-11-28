from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.comparison_cells import plan_cells,compile_cells,partition_source_bound_claims
from services.deep_research.comparison_presentation import metadata,audit_digest,revalidate_audit
from services.deep_research.comparison_intent import guidance,GUIDANCE
from services.deep_research.authored_body import decode
from services.deep_research.verification import make_evidence,verify_claims
from services.deep_research.reporting import render_report
from test_deep_research_comparison_intent import packets,obligation,QUESTION,record


def test_owned_speed_retrieval_prefers_direct_report_over_reference_timing():
    from services.deep_research.comparison_joint_reports import retain_owned_speed_result, rendered_speed_rank

    row = {'pdfId': 'p1', 'contentHash': 'h1', 'accessLevel': 'fulltext',
           'retrievalMode': 'pdf_lexical_fallback'}
    setting = {**row, 'text': 'All results are reported running on an A6000 GPU.'}
    unrelated = {**row, 'text': 'We optimize each Gaussian using camera views.'}
    direct = {**row, 'text': 'Our method achieves real-time rendering of radiance fields.'}
    foreign = {**direct, 'pdfId': 'p2'}
    wrong_version = {**direct, 'contentHash': 'h2'}
    record = {'comparisonEvaluationProtocolVersion': 10}
    assert rendered_speed_rank(direct['text'], direct_results=True) == 3
    assert retain_owned_speed_result([setting, unrelated], [foreign, wrong_version, direct],
        record, 'rendering speed', 'p1', 'h1', 2) == [setting, direct]
    assert retain_owned_speed_result([setting, unrelated], [foreign, wrong_version],
        record, 'rendering speed', 'p1', 'h1', 2) == [setting, unrelated]
    assert retain_owned_speed_result([setting, unrelated], [direct],
        record, 'compression mechanism', 'p1', 'h1', 2) == [setting, unrelated]


def test_numeric_example_read_keeps_owned_table_and_retraining_note_together():
    from services.deep_research.comparison_joint_reports import preferred_numeric_example_read

    shared = {'workId': 'p', 'ownerMaterialId': 'p', 'versionId': 'v', 'contentHash': 'h',
              'accessLevel': 'fulltext', 'obligationIds': ['example']}
    table = {**shared, 'sourceId': 'table', 'text': 'Table row 1: Baseline∗ | 40\nTable row 2: Ours | 50',
             'tableData': {'groups': [['Group A', ['FPS']]], 'rows': [[1, 'Baseline∗', ['40']], [2, 'Ours', ['50']]]}}
    note = {**shared, 'sourceId': 'note', 'text': 'We retrain Baseline using the original code on our platform, marked by ∗.'}
    mismatch = {**note, 'sourceId': 'mismatch', 'versionId': 'old'}
    goals = {'example': {'requiredSources': ['p'], 'comparisonRole': {
        'kind': 'joint', 'requestExcerpt': '数字只选一组来源和口径明确的基线对照作例子'}}}
    assert preferred_numeric_example_read([table, mismatch, note], goals, ()) == [table, note]
    assert preferred_numeric_example_read([table, mismatch, note], goals, {('table', 'h')}) == [note]
    assert preferred_numeric_example_read([table, mismatch], goals, ()) == [table]
    assert preferred_numeric_example_read([table, note], {}, ()) == []


@pytest.mark.parametrize('variant', ['misplaced', 'already_joint', 'single_source', 'ambiguous'])
def test_places_only_a_unique_two_paper_speed_criterion_in_joint_scope(variant):
    from services.deep_research.comparison_joint_reports import place_cross_paper_speed_criterion
    from services.deep_research.comparison_intent import validate_plan
    from services.deep_research.coverage import validate_plan as validate_structure
    anchor = '说明为什么不能直接拿两篇的FPS排名'
    question = '用表格比较存储与画质、渲染速度。' + anchor + '。'
    speed = {'criterionId': 'scope', 'requirement': '解释两篇论文的FPS为什么不能直接排名。',
             'responseType': 'explanation'}
    remaining = {'criterionId': 'reported', 'requirement': '说明两篇论文各自报告的画质与渲染速度。',
                 'responseType': 'explanation'}
    owner = {'obligationId': 'tradeoffs', 'question': '报告存储与画质、渲染速度。',
             'requestExcerpt': '存储与画质、渲染速度', 'searchQuery': 'reported tradeoffs',
             'purpose': 'answer_requirement', 'requiredSources': ['p1', 'p2'],
             'comparisonRole': {'kind': 'per_paper', 'label': '报告指标', 'requestExcerpt': '存储与画质、渲染速度'},
             'completionCriteria': [remaining, speed]}
    plan = [{'itemId': 'compare', 'question': question, 'obligations': [owner], 'dependencies': []}]
    if variant == 'already_joint':
        plan[0]['obligations'].append({**owner, 'obligationId': 'existing', 'question': anchor,
            'comparisonRole': {'kind': 'joint', 'label': '帧率可比性', 'requestExcerpt': anchor}})
    if variant == 'single_source':
        owner['requiredSources'] = ['p1']
    if variant == 'ambiguous':
        owner['completionCriteria'].append({**speed, 'criterionId': 'scope2'})
    original = deepcopy(plan)
    placed, changes = place_cross_paper_speed_criterion(plan, question)
    assert plan == original
    if variant != 'misplaced':
        assert placed == plan and changes == []
        return
    original_owner, joint = placed[0]['obligations']
    assert original_owner['completionCriteria'] == [remaining]
    assert joint['completionCriteria'] == [speed]
    assert joint['question'] == joint['requestExcerpt'] == anchor
    assert joint['requiredSources'] == original_owner['requiredSources'] == ['p1', 'p2']
    assert changes[0]['sourceObligationId'] == owner['obligationId']
    validate_plan(validate_structure(placed), question)
    assert place_cross_paper_speed_criterion(placed, question) == (placed, [])


@pytest.mark.parametrize('variant', ['misplaced', 'already_joint', 'single_source', 'negated'])
def test_preserves_requested_memory_choice_as_its_own_joint_target(variant):
    from services.deep_research.comparison_joint_reports import place_cross_paper_memory_advice, split_joint_deliverables
    from services.deep_research.comparison_intent import validate_plan
    from services.deep_research.coverage import validate_plan as validate_structure

    anchor = '并给出显存受限时的有条件选择建议'
    axis = '存储与画质、渲染速度'
    speed = '说明为什么不能直接拿两篇的FPS排名'
    question = f'比较{axis}。{speed}，{anchor}。'
    reported = {'criterionId': 'results', 'requirement': '分别说明报告的存储与画质。', 'responseType': 'identification'}
    advice = {'criterionId': 'advice', 'requirement': '结合可核实的存储、画质、速度和处理成本证据，提出显存受限时的有条件选择建议。',
              'responseType': 'explanation'}
    original = {'obligationId': 'tradeoffs', 'question': f'比较{axis}，{anchor}。', 'requestExcerpt': axis,
                'searchQuery': 'storage quality and rendering speed', 'purpose': 'answer_requirement',
                'requiredSources': ['p1', 'p2'],
                'comparisonRole': {'kind': 'per_paper', 'label': '报告指标', 'requestExcerpt': axis},
                'completionCriteria': [reported, advice]}
    plan = [{'itemId': 'compare', 'question': question, 'obligations': [original], 'dependencies': []}]
    if variant == 'already_joint':
        plan[0]['obligations'].append({**original, 'obligationId': 'existing', 'question': anchor,
            'comparisonRole': {'kind': 'joint', 'label': '选择建议', 'requestExcerpt': anchor}})
    elif variant == 'single_source':
        original['requiredSources'] = ['p1']
    elif variant == 'negated':
        question = f'比较{axis}。不要给出显存受限时的有条件选择建议。'

    before = deepcopy(plan)
    placed, changes = place_cross_paper_memory_advice(plan, question)
    assert plan == before
    if variant != 'misplaced':
        assert (placed, changes) == (before, [])
        return
    factual, joint = placed[0]['obligations']
    assert factual['completionCriteria'] == [reported]
    assert joint['completionCriteria'] == [advice]
    assert joint['question'] == joint['requestExcerpt'] == anchor
    assert joint['requiredSources'] == factual['requiredSources'] == ['p1', 'p2']
    assert changes[0]['criterionId'] == 'advice'
    validate_plan(validate_structure(placed), question)
    assert place_cross_paper_memory_advice(placed, question) == (placed, [])
    requirements = [factual, joint]
    roles = {row['obligationId']: row['comparisonRole'] for row in requirements}
    assert split_joint_deliverables(roles, requirements, question, classify_standalone=True,
        standalone_memory_scope=True)[joint['obligationId']] == [{'kind': 'conditional_advice', 'requirement': anchor}]


def fixture(marked=True):
    cp,_=packets()
    question=QUESTION+'数字只选一组同口径基线对照。'
    target=obligation('example','joint','同口径数字','数字只选一组')
    target.update(requiredSourceAliases=['P1','P2'],requestExcerpt='数字只选一组同口径基线对照')
    target['completionCriteria']=[{'criterionId':'matched','requirement':'给一组同口径基线数字，保留条件。','responseType':'identification'}]
    requirements=[*cp['requirements'],target]
    quote='Table row 1: Baseline | 100 | 10MB\nTable row 2: Variant | 150 | 6MB'
    ev=make_evidence({'workId':'left','versionId':'left-v1','contentHash':'hash','accessLevel':'fulltext'},
        quote,quote,location={'table':'t1'},obligation_ids=['example'])
    ev['tableData']={'groups':[['Bench',['FPS','Size']]],'rows':[[1,'Baseline',['100','10MB']],[2,'Variant',['150','6MB']]]}
    wire={'evidenceId':'E1','source':'P1','obligations':['example'],'quote':quote,'tableData':ev['tableData']}
    cp=plan_cells(requirements,cp['sources'],[wire],shared_axes=True,typed_roles=True,question=question,joint_reports=marked)
    bindings=[{'evidenceId':'E1','rowNumber':n,'groupIndex':0,'metric':m,'value':v}
        for n,_,values in ev['tableData']['rows'] for m,v in zip(['FPS','Size'],values)]
    point={'kind':'reported','body':{'prose':{'text':'Bench 同口径结果：Baseline FPS 100、Size 10MB；Variant FPS 150、Size 6MB。','conditions':{}}},
           'evidenceRefs':['E1'],'tableBindings':bindings,'detailLevel':'concise'}
    payload={'cells':[],'conclusions':[{'obligationIds':['example'],'claim':point}]}
    return cp,payload,ev,question


def compiled():
    cp,payload,ev,question=fixture();draft=compile_cells(payload,cp,max_claims=5);draft['sources']=cp['sources']
    c=decode(draft['report']['claims'][0]);c['evidenceRefs']=[ev['evidenceId']]
    for b in c['tableBindings']:b['evidenceId']=ev['evidenceId']
    return cp,draft,c,ev,question


def test_shared_reported_example_does_not_force_a_second_source_or_waive_other_goals():
    cp,draft,claim,ev,_=compiled()
    assert draft['jointReports'] is True and claim['kind']=='reported'
    assert not any(c['obligationId']=='example' for c in cp['cells'])
    assert len(cp['cells'])==2 and {'mechanism','fairness','choice'}<=set(draft['unresolvedObligationIds'])
    retained,rejected=partition_source_bound_claims([claim],draft,[ev])
    assert retained==[claim] and not rejected
    check=Mock(return_value=[{'claimId':claim['claimId'],'status':'passed'}])
    verified=verify_claims([claim],[ev],check,table_references_version=4)
    assert len(verified['accepted'])==1
    assert verified['accepted'][0]['kind']=='reported' and verified['accepted'][0]['verification']=='semantic_passed'
    assert verified['accepted'][0]['text']==claim['text']
    text=render_report({'claims':verified['accepted'],'evidence':[ev],'comparisonCells':metadata(draft),
                        'outputKind':'paper_comparison','presentationVersion':4})
    assert claim['text'] in text and '10MB' in text and '6MB' in text


def test_measurement_protocol_keeps_actual_reported_settings_in_bounded_slots():
    from services.deep_research.comparison_joint_reports import comparison_protocol_priority
    from services.deep_research.reading_priority import select_read_sources

    def paper(sid, work, text, **fields):
        return {'sourceId': sid, 'workId': work, 'versionId': work + '-v1',
                'accessLevel': 'fulltext', 'text': text, 'location': {}, **fields}

    generic = paper('generic', 'left', 'We can render high-quality views on consumer GPU hardware.')
    settings = paper('hardware', 'left',
                     'All results are reported running on an A6000 GPU, except for one evaluation.')
    second = paper('second', 'right', 'All performance evaluations are conducted on an RTX GPU.')
    foreign = paper('foreign', 'out-of-scope', settings['text'])
    abstract = {**settings, 'sourceId': 'summary', 'accessLevel': 'abstract'}
    rows = [generic, foreign, abstract, settings, second]
    obligations = {'comparison': {'obligationId': 'comparison',
                                  'question': '比较 FPS 前需要说明什么硬件条件？',
                                  'requiredSources': ['left', 'right']}}
    selected = select_read_sources(rows, obligations, 6, comparison_evaluation_protocol=True)
    assert [row['sourceId'] for row in selected[:2]] == ['hardware', 'second']
    assert len(selected) == 4 and foreign not in selected
    candidates = [{**row, 'source': row['workId'], 'evidenceId': row['sourceId'], 'quote': row['text']}
                  for row in rows]
    targets = [{'role': 'joint', 'sources': ['left', 'right'], 'question': '为什么 FPS 不能直接比较？'}]
    assert comparison_protocol_priority(candidates, targets, reported_platform=True) == {'hardware', 'second'}
    targets[0]['deliverable'] = 'comparability'
    assert not comparison_protocol_priority(candidates, targets, reported_platform=True)
    assert comparison_protocol_priority(candidates, targets, reported_platform=True, explicit_targets=True) == {'hardware', 'second'}


def test_speed_retrieval_retains_protocol_only_from_the_same_pdf_snapshot():
    from services.deep_research.comparison_joint_reports import retain_evaluation_protocol

    paper = {'pdfId': 'left', 'contentHash': 'current', 'accessLevel': 'fulltext',
             'retrievalMode': 'pdf_lexical_fallback'}
    generic = {**paper, 'sourceId': 'generic', 'text': 'We present real-time visualization.'}
    table = {**generic, 'sourceId': 'table', 'tableData': {'rows': []}}
    protocol = {**paper, 'sourceId': 'protocol',
                'text': 'All results are reported running on an A6000 GPU, except another evaluation.'}
    stale = {**protocol, 'sourceId': 'old', 'contentHash': 'stale'}
    foreign = {**protocol, 'sourceId': 'foreign', 'pdfId': 'right'}
    abstract = {**protocol, 'sourceId': 'abstract', 'accessLevel': 'abstract'}
    rows = [generic, table]
    candidates = [generic, stale, foreign, abstract, protocol]
    current = {'comparisonEvaluationProtocolVersion': 3}
    assert retain_evaluation_protocol(
        rows, candidates, current, 'FPS evaluation hardware', 'left', 'current', 2) == [protocol, table]
    assert retain_evaluation_protocol(
        rows, candidates[:-1], current, 'FPS evaluation hardware', 'left', 'current', 2) == rows
    assert retain_evaluation_protocol(
        rows, candidates, current, 'model compression mechanism', 'left', 'current', 2) == rows
    assert retain_evaluation_protocol(
        rows, candidates, {'comparisonEvaluationProtocolVersion': 2},
        'FPS evaluation hardware', 'left', 'current', 2) == rows


def test_optional_speed_premise_requires_a_source_local_comparison_sentence():
    from services.deep_research.comparison_joint_reports import preferred_speed_result

    paper = {'source': 'P2', 'accessLevel': 'fulltext'}
    truncated = {**paper, 'evidenceId': 'fragment',
                 'quote': '-GS on the benchmark, nearly doubling rendering speed.'}
    reported = {**paper, 'evidenceId': 'comparison',
                'quote': 'Our method outperforms Method A on the benchmark, nearly doubling rendering speed.'}
    rows = [truncated, {**reported, 'source': 'P1', 'evidenceId': 'foreign'},
            {**reported, 'accessLevel': 'abstract', 'evidenceId': 'abstract'}, reported]
    targets = [{'role': 'paper_cell', 'source': 'P2', 'question': '渲染速度'}]
    assert preferred_speed_result(rows, targets, 'P2') == ('comparison',)
    assert not preferred_speed_result(rows[:-1], targets, 'P2')
    assert not preferred_speed_result(rows, [{**targets[0], 'question': '压缩机制'}], 'P2')


def test_deployment_memory_context_stays_in_the_active_source_and_target_scope():
    from services.deep_research.comparison_joint_reports import deployment_memory_priority, preferred_deployment_memory_reads
    from services.deep_research.general_advice import has_device_memory_measurement

    prose = 'Rendering requires GPU memory for the model and an additional 30–500 MB rasterizer buffer.'
    context = {'sourceId': 'context', 'workId': 'p', 'versionId': 'p-v1',
               'location': {}, 'text': prose, 'accessLevel': 'fulltext'}
    foreign = {**context, 'sourceId': 'foreign', 'workId': 'q', 'versionId': 'q-v1'}
    summary = {**context, 'sourceId': 'summary', 'accessLevel': 'abstract'}
    training = {**context, 'sourceId': 'train', 'text': 'During training peak GPU memory was 20 GB.'}
    options = [summary, foreign, training, context]
    active = {'advice': {'obligationId': 'advice', 'question': '显存受限时如何选择？', 'requiredSources': ['p']}}
    assert preferred_deployment_memory_reads(options, active, 12, ()) == [context]
    assert preferred_deployment_memory_reads(options, active, 12, {('context', None)}) == []
    assert preferred_deployment_memory_reads(options, active, 5, ()) == []
    rows = [{**row, 'evidenceId': row['sourceId'], 'source': row['workId'], 'quote': row['text']} for row in options]
    targets = [{'deliverable': 'conditional_advice', 'question': '显存受限时如何选择？',
                'evidenceIds': ['context', 'train']}]
    assert deployment_memory_priority(rows, targets) == {'context'}
    assert not has_device_memory_measurement(prose, direct=True)


def test_standalone_memory_choice_uses_user_anchor_after_planner_rephrases_goal():
    from services.deep_research.comparison_joint_reports import split_joint_deliverables

    anchor = '显存受限时的有条件选择建议'
    requirement = '说明显存受限情形下选择原始表示或压缩部署的适用条件'
    roles = {'choice': {'kind': 'joint', 'requestExcerpt': anchor}}
    goals = [{'obligationId': 'choice', 'question': requirement,
              'completionCriteria': [{'criterionId': 'choice', 'requirement': requirement}]}]
    assert split_joint_deliverables(roles, goals, anchor, classify_standalone=True) == {}
    options = dict(classify_standalone=True, standalone_memory_scope=True)
    assert split_joint_deliverables(roles, goals, anchor, **options) == {
        'choice': [{'kind': 'conditional_advice', 'requirement': requirement}],
    }
    goals[0]['completionCriteria'][0]['requirement'] += '并比较两篇的 FPS'
    assert split_joint_deliverables(roles, goals, anchor, **options) == {}


def test_user_memory_advice_survives_narrow_speed_role_without_changing_scope():
    from services.deep_research.comparison_joint_reports import (
        preferred_deployment_memory_reads, preserve_requested_memory_advice, split_joint_deliverables,
    )
    speed = '为什么不能直接拿两篇的FPS排名'
    advice = '并给出显存受限时的有条件选择建议'
    literal = f'说明能比较什么、{speed}，{advice}'
    role = {'kind': 'joint', 'requestExcerpt': speed}
    obligation = {'obligationId': 'choice', 'question': speed, 'requestExcerpt': literal,
                  'comparisonRole': role, 'requiredSources': ['left', 'right'],
                  'completionCriteria': [{'criterionId': 'speed', 'requirement': speed,
                                          'responseType': 'explanation'}]}
    plan = [{'itemId': 'compare', 'obligations': [obligation]}]
    updated, changes = preserve_requested_memory_advice(plan, literal)
    revised, = updated[0]['obligations']
    assert changes == [{'obligationId': 'choice', 'change': 'preserved_memory_advice'}]
    assert revised['requiredSources'] == obligation['requiredSources']
    assert updated != plan and len(obligation['completionCriteria']) == 1
    assert preserve_requested_memory_advice(updated, literal) == (updated, [])
    assert preserve_requested_memory_advice(plan, speed) == (plan, [])
    split = split_joint_deliverables({'choice': role}, [revised], literal, split_speed_and_advice=True)
    assert split['choice'] == [{'kind': 'comparability', 'requirement': speed},
                               {'kind': 'conditional_advice', 'requirement': advice}]
    page = {'sourceId': 'context', 'workId': 'left', 'versionId': 'v1',
            'accessLevel': 'fulltext', 'text': 'Rendering requires GPU memory for the trained model.'}
    foreign = {**page, 'sourceId': 'foreign', 'workId': 'outside'}
    assert preferred_deployment_memory_reads([foreign, page], {'choice': revised}, 12, ()) == []
    assert preferred_deployment_memory_reads([foreign, page], {'choice': revised}, 12, (),
                                             completion_criteria=True) == [page]


@pytest.mark.parametrize('change', [None, 'ordinary_gap', 'partial_audit', 'invalid_audit', 'stale_layout',
                                   'wrong_version', 'wrong_value', 'missing_bindings', 'unverified'])
def test_verified_same_table_example_closes_only_the_joint_readiness_gap(change):
    from services.deep_research.final_coverage import remaining_retrieval_gaps

    _, draft, claim, ev, _ = compiled()
    draft['benchmarkExampleClaimId'] = claim['claimId']
    draft['jointDeliverables'] = {'example': [{'kind': 'matched_example', 'requirement': '给出同表对照'}]}
    claim['verification'] = 'semantic_passed'
    gap = {'obligationId': 'example', 'sourceWorkId': 'right', 'question': '给出同表对照',
           'missingEvidence': 'Earlier assessment did not find the complete comparison.'}
    coverage = [{**gap, 'supportKind': 'joint', 'state': 'unchecked'}]
    advice_gap = {**gap, 'obligationId': 'choice'}
    verdict = {'obligationId': 'example', 'status': 'covered',
               'bindings': [{'claimId': claim['claimId'], 'field': 'text', 'excerpt': claim['text']}]}
    if change == 'ordinary_gap':
        coverage[0]['supportKind'] = 'regular'
    if change == 'partial_audit':
        verdict['status'] = 'partial'
    if change == 'wrong_version':
        ev['sourceVersionId'] = 'left-v2'
    if change == 'wrong_value':
        claim['tableBindings'][0]['value'] = '999'
    if change == 'missing_bindings':
        claim['tableBindings'] = []
    if change == 'unverified':
        claim['verification'] = 'unchecked'
    audit = {'status': 'invalid_response' if change == 'invalid_audit' else 'checked',
             'gaps': [], 'verdicts': [verdict],
             'comparisonPresentationDigest': audit_digest(metadata(draft), [claim])}
    if change == 'stale_layout':
        audit['comparisonPresentationDigest'] = 'obsolete'
    gaps = [gap, advice_gap]
    originals = deepcopy((gaps, coverage, audit, claim, ev))
    assert remaining_retrieval_gaps(gaps, audit, [claim], [ev]) == gaps
    assert remaining_retrieval_gaps(gaps, audit, [claim], [ev], comparison_draft=draft,
                                    joint_coverage=coverage) == ([advice_gap] if change is None else gaps)
    assert (gaps, coverage, audit, claim, ev) == originals


def test_historical_compiler_still_refuses_reported_joint_and_prompt_is_unchanged():
    cp,payload,_,_=fixture(False);draft=compile_cells(payload,cp,max_claims=5)
    assert not draft['report']['claims'] and draft['errors']
    assert 'jointReports' not in cp and 'jointReports' not in draft
    r=record();assert guidance(r)==GUIDANCE
    r.update(comparisonPlanningContractVersion=2,comparisonJointReportsContractVersion=1)
    assert 'SINGLE baseline example' in guidance(r) and 'not a separate numerical inventory' in guidance(r)


def test_beginner_mechanism_guidance_is_scoped_to_paper_cells_and_new_runs():
    from services.deep_research.comparison_wire import render

    cp, _ = packets()
    question = '向初学者解释。' + QUESTION
    cp = plan_cells(cp['requirements'], cp['sources'], list(cp['evidence'].values()), shared_axes=True,
                    typed_roles=True, question=question, fixed_slots=True, unified_answers=True,
                    local_goal_refs=True, measurement_display=True)
    r = record()
    r.update(question=question, comparisonAuthoringContractVersion=16,
             comparisonJointReportsContractVersion=16, comparisonEvaluationProtocolVersion=7,
             comparisonPlanningContractVersion=6, comparisonReviewBatchContractVersion=3)
    r['state']['outputKind'] = 'paper_comparison'
    marker = 'Naming the step or giving its benefit alone is insufficient.'
    historic = render(r, question, cp, {}, None, 4, source_scope=('P1',))
    r['comparisonBeginnerMechanismGuidanceVersion'] = 1
    authored = render(r, question, cp, {}, None, 4, source_scope=('P1',))
    assert marker not in historic and marker in authored
    assert 'what guides it and why it matters when the cited passage supports that explanation' in authored
    assert marker not in render(r, question, cp, {}, None, 4, source_scope=('joint',))
    r['comparisonBeginnerMechanismGuidanceVersion'] = 2
    plain = 'At first use, explain each essential technical term in ordinary Chinese beside it.'
    assert plain not in authored
    assert plain in render(r, question, cp, {}, None, 4, source_scope=('P1',))
    assert plain not in render(r, question, cp, {}, None, 4, source_scope=('joint',))
    r['question'] = QUESTION
    assert render(r, QUESTION, cp, {}, None, 4, source_scope=('P1',)) == render(
        {**r, 'comparisonBeginnerMechanismGuidanceVersion': 0}, QUESTION, cp, {}, None, 4, source_scope=('P1',))


def test_compression_prompt_surfaces_pruning_recovery_only_for_the_paper_with_a_direct_passage():
    from services.deep_research.comparison_wire import render

    cp, _ = packets()
    question = '向初学者解释。' + QUESTION
    rows = list(cp['evidence'].values())
    rows[0] = {**rows[0], 'quote': 'We recover lost details after pruning redundant Gaussians.'}
    plan = plan_cells(cp['requirements'], cp['sources'], rows, shared_axes=True, typed_roles=True,
                      question=question, fixed_slots=True, unified_answers=True, local_goal_refs=True,
                      measurement_display=True)
    r = record()
    r.update(question=question, comparisonAuthoringContractVersion=16, comparisonJointReportsContractVersion=16,
             comparisonEvaluationProtocolVersion=7, comparisonPlanningContractVersion=6,
             comparisonReviewBatchContractVersion=3, comparisonBeginnerMechanismGuidanceVersion=5)
    cue = 'why the cited pruning and recovery steps are used'
    assert cue in render(r, question, plan, {}, None, 4, source_scope=('P1',))
    assert cue not in render(r, question, plan, {}, None, 4, source_scope=('P2',))
    assert cue not in render({**r, 'comparisonBeginnerMechanismGuidanceVersion': 4}, question,
                             plan, {}, None, 4, source_scope=('P1',))


def test_memory_advice_prompt_requests_cited_reasoning_before_measured_choice():
    from services.deep_research.comparison_wire import render, resolve_point, targets

    cp, _ = packets()
    question = '向初学者解释。' + QUESTION + ' 给出显存受限时的有条件选择建议。'
    plan = plan_cells(cp['requirements'], cp['sources'], list(cp['evidence'].values()),
                      shared_axes=True, typed_roles=True, question=question, fixed_slots=True,
                      unified_answers=True, local_goal_refs=True, measurement_display=True,
                      structured_test_first=True)
    joint = next(oid for oid, role in plan['roles'].items() if role['kind'] == 'joint')
    plan['jointDeliverables'] = {joint: [{'kind': 'conditional_advice', 'requirement': '给出显存受限时的有条件选择建议。'}]}
    plan['structuredTestFirst'] = True
    r = record()
    r.update(question=question, comparisonAuthoringContractVersion=16, comparisonJointReportsContractVersion=16,
             comparisonPlanningContractVersion=6, comparisonReviewBatchContractVersion=3,
             comparisonBeginnerDeploymentGuidanceVersion=2)
    current = render(r, question, plan, {}, None, 3, source_scope=('joint',))
    old = render({**r, 'comparisonBeginnerDeploymentGuidanceVersion': 1}, question,
                 plan, {}, None, 3, source_scope=('joint',))
    assert 'Cite actual observations that inform' in current
    assert 'body={"deviceMemoryAdvice":"measure_then_choose"}' in old
    assert 'body={"deviceMemoryAdvice":"measure_then_choose"}' not in current
    structured = render({**r, 'comparisonBeginnerDeploymentGuidanceVersion': 3}, question,
                        plan, {}, None, 3, source_scope=('joint',))
    assert 'point.memoryCandidates' in structured
    assert 'point.memoryCandidates' not in current
    target = next(t for t in targets(plan) if t.get('deliverable') == 'conditional_advice')
    point = {'kind': 'proposal', 'evidenceRefs': target['evidenceIds'][:1], 'cellRefs': [],
             'body': {'prose': {'text': '同一硬件和场景先实测两种方法的峰值显存，画质达标后再选择。', 'conditions': {}}}}
    assert resolve_point(point, target, {})['body'] == point['body']
    point['body']['prose']['text'] += ' 推荐使用方法 A。'
    with pytest.raises(ValueError, match='device_memory_test_first'):
        resolve_point(point, target, {})


@pytest.mark.parametrize('mutation',['foreign','version','goal'])
def test_edited_example_keeps_exact_goal_and_source_version_scope(mutation):
    _,draft,c,ev,_=compiled()
    if mutation=='foreign':ev['sourceWorkId']='other'
    elif mutation=='version':ev['sourceVersionId']='left-v2'
    else:c['obligationIds']=['mechanism']
    accepted,rejected=partition_source_bound_claims([c],draft,[ev])
    assert not accepted and rejected[0]['reason']=='comparison_joint_scope_mismatch'


@pytest.mark.parametrize('mutation',['value','metric','row','dataset','negative_semantic'])
def test_reported_kind_preserves_numeric_and_independent_semantic_checks(mutation):
    _,_,c,ev,_=compiled()
    if mutation=='value':c['tableBindings'][0]['value']='999'
    elif mutation=='metric':c['tableBindings'][0]['metric']='PSNR'
    elif mutation=='row':c['tableBindings'][0]['rowNumber']=99
    elif mutation=='dataset':c['text']=c['text'].replace('Bench','Other')
    checker=Mock(return_value=[{'claimId':c['claimId'],'status':'failed' if mutation=='negative_semantic' else 'passed'}])
    assert not verify_claims([c],[ev],checker,table_references_version=4)['accepted']


@pytest.mark.parametrize(('mutation', 'expected'), [
    ('unchanged', None), ('another_claim', 'comparison_benchmark_example_scope'),
    ('another_group', 'comparison_benchmark_example_pair'),
    ('asymmetric_metrics', 'comparison_benchmark_example_pair'),
])
def test_benchmark_owner_and_pair_survive_repair_and_publication_checks(mutation, expected):
    from services.deep_research.comparison_joint_reports import bind_benchmark_example
    plan, draft, claim, evidence, _ = compiled()
    plan['jointDeliverables'] = {'example': [{'kind': 'matched_example', 'requirement': '一组基准数字'}]}
    bind_benchmark_example({'comparisonJointReportsContractVersion': 5}, draft, plan)
    assert 'benchmarkExampleClaimId' not in draft
    bind_benchmark_example({'comparisonJointReportsContractVersion': 6}, draft, plan)
    assert draft['benchmarkExampleClaimId'] == claim['claimId']
    if mutation == 'another_claim':
        claim['claimId'] = 'revised_other_claim'
    elif mutation == 'another_group':
        claim['tableBindings'][0]['groupIndex'] = 1
    elif mutation == 'asymmetric_metrics':
        claim['tableBindings'].pop()
    kept, rejected = partition_source_bound_claims([claim], draft, [evidence])
    assert (rejected[0]['reason'] if rejected else None) == expected
    assert kept == ([] if expected else [claim])


@pytest.mark.parametrize(('text', 'conditions', 'blocked'), [
    ('两个合成场景上达到 180–300 FPS。', {}, True),
    ('渲染速度见测试条件。', {'fps': 200}, True),
    ('渲染速度超过 200 帧/秒。', {}, True),
    ('渲染速度约 200 frames per second。', {}, True),
    ('论文报告在该合成场景下可实时渲染。', {}, False),
    ('以 FPS 衡量速度，额外训练 5 分钟。', {'硬件': 'RTX 4090'}, False),
])
def test_only_joint_example_can_use_numerical_frame_rate(text, conditions, blocked):
    from services.deep_research.comparison_joint_reports import benchmark_binding_error, bind_benchmark_example

    plan, draft, example, _, _ = compiled()
    plan['jointDeliverables'] = {'example': [{'kind': 'matched_example', 'requirement': '一组基准数字'}]}
    claim = {'claimId': 'paper_cell', 'text': text, 'conditions': conditions, 'tableBindings': []}
    record = {'comparisonJointReportsContractVersion': 16}
    bind_benchmark_example(record, draft, plan)
    assert benchmark_binding_error(claim, draft) is None
    bind_benchmark_example({**record, 'comparisonBenchmarkSpeedScopeContractVersion': 1}, draft, plan)
    assert draft['benchmarkExampleClaimId'] == example['claimId']
    assert benchmark_binding_error(claim, draft) == ('comparison_benchmark_example_scope' if blocked else None)
    assert benchmark_binding_error({**claim, 'claimId': example['claimId']}, draft) is None


@pytest.mark.parametrize(('text', 'conditions', 'blocked'), [
    ('在 Tank & Temple 上，渲染速度相较基线接近翻倍。', {}, True),
    ('渲染速度提高约 30%。', {}, True),
    ('渲染速度提高了 2.5 倍。', {}, True),
    ('Frame rate nearly doubled on this dataset.', {}, True),
    ('The method doubles the reported rendering speed.', {}, True),
    ('It reaches twice the baseline rendering speed.', {}, True),
    ('转到测试口径。', {'相对帧率': '接近翻倍'}, True),
    ('渲染速度更快，存储缩小三倍。', {}, False),
    ('渲染速度更快，训练在RTX A6000上完成。', {}, False),
    ('提速来自排序优化。', {'训练迭代次数': '提高了两倍'}, False),
])
def test_lexical_frame_rate_ratios_belong_to_the_single_numeric_example(text, conditions, blocked):
    from services.deep_research.comparison_joint_reports import benchmark_binding_error

    claim = {'claimId': 'paper_cell', 'text': text, 'conditions': conditions, 'tableBindings': []}
    draft = {'benchmarkExampleClaimId': 'example', 'benchmarkSpeedScopeVersion': 3}
    assert benchmark_binding_error(claim, draft) == ('comparison_benchmark_example_scope' if blocked else None)
    assert benchmark_binding_error({**claim, 'claimId': 'example'}, draft) is None
    assert benchmark_binding_error(claim, {**draft, 'benchmarkSpeedScopeVersion': 2}) is None


@pytest.mark.parametrize(('attribute', 'value', 'suffix', 'expected'), [
    ('GPU', 'RTX A6000', '', None),
    ('FPS', '200', '', 'comparison_benchmark_example_scope'),
    ('GPU', 'RTX A6000', '第一篇实测 200 FPS。', 'comparison_benchmark_example_scope'),
])
def test_boundary_keeps_paper_title_out_of_frame_rate_check(attribute, value, suffix, expected):
    from services.deep_research.comparison_joint_reports import benchmark_binding_error
    from services.deep_research.scope_expression import materialize

    title = 'A Paper with 200+ FPS'
    boundary = {
        'observedSettings': [{'subject': title, 'attribute': attribute, 'value': value}],
        'notEstablished': [
            {'type': 'comparison_evidence', 'subjects': [title, 'Second paper'], 'quantity': 'FPS排名'}
        ],
    }
    claim = {'claimId': 'boundary', 'kind': 'inference', 'text': '', 'conditions': {},
             'scopeExpression': boundary, 'tableBindings': []}
    claim, _ = materialize(claim, 5)
    claim['text'] += suffix
    draft = {
        'benchmarkExampleClaimId': None, 'benchmarkSpeedScopeVersion': 1,
        'sources': {'P1': {'title': title}, 'P2': {'title': 'Second paper'}},
        'report': {'claims': [{'claimId': 'boundary', 'body': {'boundary': boundary}}]},
    }
    assert benchmark_binding_error(claim, draft) == expected


@pytest.mark.parametrize(('text', 'expected'), [
    ('LightGaussian 的 FPS 为 237，在另一数据集上为 357。', 'comparison_benchmark_example_scope'),
    ('帧率约为 180。', 'comparison_benchmark_example_scope'),
    ('平均FPS为237。', 'comparison_benchmark_example_scope'),
    ('FPS was 237 on the benchmark.', 'comparison_benchmark_example_scope'),
    ('两篇 FPS 的测量口径未对齐。', None),
])
def test_one_example_detects_frame_rate_values_after_verbs(text, expected):
    from services.deep_research.comparison_joint_reports import benchmark_binding_error

    claim = {'claimId': 'speed', 'text': text, 'conditions': {}}
    draft = {'benchmarkExampleClaimId': 'example', 'benchmarkSpeedScopeVersion': 1}
    assert benchmark_binding_error(claim, draft) is None
    draft['benchmarkSpeedScopeVersion'] = 2
    assert benchmark_binding_error(claim, draft) == expected
    assert benchmark_binding_error({**claim, 'claimId': 'example'}, draft) is None


@pytest.mark.parametrize('mutation',['policy','kind','text','binding','reference'])
def test_reported_policy_and_joint_fact_are_bound_to_final_audit_digest(mutation):
    _,draft,c,_,_=compiled();meta=metadata(draft)
    audit={'comparisonPresentationDigest':audit_digest(meta,[c]),'gaps':[]}
    assert revalidate_audit(audit,meta,[c])==audit
    if mutation=='policy':meta.pop('jointReports')
    elif mutation=='kind':c['kind']='inference'
    elif mutation=='text':c['text']+=' New unsupported scope.'
    elif mutation=='binding':c['tableBindings'][0]['value']='999'
    else:c['evidenceRefs']=['foreign']
    assert revalidate_audit(audit,meta,[c])['status']=='invalidated_comparison_presentation'


def test_server_selects_and_freezes_joint_report_policy(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.comparison_generation import planning_options
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **kwargs:None,llm_client=object(),comparison_cells_version=1,
                          comparison_review_batch_version=1)
    try:
        r,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':QUESTION,'outputKind':'paper_comparison',
            'comparisonJointReportsContractVersion':0},start_async=False)
        assert r['comparisonJointReportsContractVersion']==16
        assert r['comparisonBenchmarkSpeedScopeContractVersion'] == 7
        assert r['comparisonRepairFlowContractVersion'] == 3
        assert r['comparisonStageAbstentionContractVersion'] == 1
        assert r['comparisonPaperWordingContractVersion'] == 3
        r=repo.update_run(r['runId'],lambda r:{**r,'state':{**r.get('state',{}),'outputKind':'paper_comparison'}})
        assert planning_options(r,QUESTION)['joint_reports'] is True
        with pytest.raises(ValueError, match='Immutable'):
            repo.update_run(r['runId'], lambda current: {
                **current, 'comparisonRepairFlowContractVersion': 1})
        for value in [0,None,True]:
            with pytest.raises(ValueError,match='Immutable'):
                repo.update_run(r['runId'],lambda current:{**current,'comparisonJointReportsContractVersion':value})
            with pytest.raises(ValueError, match='Immutable'):
                repo.update_run(r['runId'], lambda current: {
                    **current, 'comparisonBenchmarkSpeedScopeContractVersion': value})
            with pytest.raises(ValueError, match='Immutable'):
                repo.update_run(r['runId'], lambda current: {
                    **current, 'comparisonRepairFlowContractVersion': value})
            with pytest.raises(ValueError, match='Immutable'):
                repo.update_run(r['runId'], lambda current: {
                    **current, 'comparisonStageAbstentionContractVersion': value})
            with pytest.raises(ValueError, match='Immutable'):
                repo.update_run(r['runId'], lambda current: {
                    **current, 'comparisonPaperWordingContractVersion': value})
    finally:facade.shutdown()


def test_actual_synthesis_compiles_joint_report_and_preserves_all_other_targets():
    from services.deep_research.graph import make_synthesize_node
    cp,payload,ev,question=fixture();current=record()
    current.update(runId='r',question=question,comparisonPlanningContractVersion=2,comparisonJointReportsContractVersion=1)
    requirements=cp['requirements']
    current['state'].update(evidence=[ev],outputKind='paper_comparison',plan=[
        {'itemId':'facts','question':'mechanism','obligations':requirements[:1]},
        {'itemId':'judgement','question':'comparison','obligations':requirements[1:3]},
        {'itemId':'example','question':'one matched example','obligations':requirements[3:]}])
    before=deepcopy(current['state']['evidence']);sent=[]
    def update(rid,fn,**kwargs):
        nonlocal current
        current=fn(deepcopy(current));return deepcopy(current)
    def invoke(rid,node,prompt,options,**kwargs):
        assert node=='synthesize' and 'Joint answer targets' in prompt
        assert 'kind=reported' in prompt and 'ACROSS the whole answer' in prompt
        sent.append(prompt);return {'content':json.dumps(payload)}
    result=make_synthesize_node(invoke,update)({'run_id':current['runId']})
    assert not result.get('error_code') and len(sent)==1
    draft=current['state']['comparisonCellDraft']
    assert draft['jointReports'] is True and {'mechanism','fairness','choice'}<=set(draft['unresolvedObligationIds'])
    claims=current['state']['reportBody']['claims']
    assert len(claims)==1 and claims[0]['kind']=='reported' and claims[0]['evidenceRefs']==[ev['evidenceId']]
    assert current['state']['evidence']==before and not current['state'].get('verifiedReport')


def test_example_alone_does_not_pass_complete_question_audit():
    from services.deep_research.final_coverage import audit_final_answer
    from test_deep_research_comparison_audit import decode as decode_prompt
    from services.deep_research.structured_output import normalize
    cp,draft,c,ev,question=compiled();sent=[]
    def invoke(rid,node,prompt,options,**kwargs):
        data=decode_prompt(prompt);sent.append(data);rows=[]
        for obligation in data['requirements']:
            checks=[]
            for required in obligation['checks']:
                row={'checkId':required['checkId'],'status':'missing','bindings':[],
                     'reason':'The numerical example does not supply the requested mechanisms and choices.'}
                if required.get('responseType')=='limitation':row['limitSpans']=[]
                if required.get('processRequired'):row['processLinks']=[]
                checks.append(row)
            rows.append({'obligationId':obligation['obligationId'],'checks':checks})
        return normalize(node,{'content':json.dumps({'items':rows,'auditType':'answer_coherence','coherent':True,'issues':[]})},comparison_audit_envelope=True)
    plan=[{'obligations':cp['requirements']}]
    result=audit_final_answer('r',question,plan,[c],[ev],invoke,json.loads,request_contract=5,
        diagnostics=True,coherence=True,shared_decision_inputs=True,shared_evidence_context=True,
        consolidated_instructions=True,literal_limits=True,comparison_cells=metadata(draft),comparison_audit_envelope=True)
    assert len(sent)==1 and result['gaps']
    assert {'mechanism','fairness','choice'}<={gap['obligationId'] for gap in result['gaps']}


def test_new_joint_input_removes_conflicting_kind_rule_and_preserves_other_cells():
    from services.deep_research.comparison_generation import render
    cp, _, ev, question = fixture(); current = record()
    current.update(comparisonPlanningContractVersion=2,comparisonJointReportsContractVersion=2)
    wire=[{'evidenceId':'E1','source':'P1','obligations':['example'],'quote':ev['quote'],'tableData':ev['tableData']}]
    old=render(current,question,cp['requirements'],cp['sources'],wire,{},None,8)
    current['comparisonJointReportsContractVersion']=3
    new=render(current,question,cp['requirements'],cp['sources'],wire,{},None,8)
    assert 'conclusions, kind inference/proposal/suggestion' in old
    assert 'conclusions, kind inference/proposal/suggestion' not in new
    assert 'Answer EACH joint target' in new and 'does not replace qualitative entries' in new
    marker='Cell routing and citation permissions (metadata, not evidence):\n'
    assert json.JSONDecoder().raw_decode(old.split(marker,1)[1])[0]==json.JSONDecoder().raw_decode(new.split(marker,1)[1])[0]
def test_named_condition_bound_result_requires_condition_in_the_quoted_result():
    from services.deep_research.comparison_joint_reports import named_condition_bound_result

    quote = 'Our method achieves the best result at matching thresh-\nolds of 6.5 pixels or more.'
    evidence = {'accessLevel': 'fulltext', 'quote': quote,
                'sourceContext': {'before': 'BenchMark-X uses pairwise matching.'}}
    assert named_condition_bound_result(evidence, {'benchmark-x'})
    assert not named_condition_bound_result(evidence, {'benchmark-y'})
    assert not named_condition_bound_result({**evidence, 'accessLevel': 'abstract'}, {'benchmark-x'})

    separate_sentences = 'Our method improves accuracy. We set the matching threshold to 6.5 pixels.'
    assert not named_condition_bound_result({**evidence, 'quote': separate_sentences}, {'benchmark-x'})


def test_named_feature_matching_counts_require_printed_columns_and_own_figure_caption():
    from services.deep_research.comparison_joint_reports import named_feature_matching_counts

    quote = ('Method # Features # Matches\nMethod A 1.2K 920\nMethod B 3K 1.4K\n'
             'Figure 2: Evaluation on BenchMark-X image pairs.')
    evidence = {'accessLevel': 'fulltext', 'quote': quote}
    assert named_feature_matching_counts(evidence, {'benchmark-x'})
    assert not named_feature_matching_counts(evidence, {'benchmark-y'})
    assert not named_feature_matching_counts({**evidence, 'quote': quote.replace('# Matches', 'Score')}, {'benchmark-x'})
    assert not named_feature_matching_counts({**evidence, 'quote': quote.replace('3K 1.4K', '3K')}, {'benchmark-x'})
