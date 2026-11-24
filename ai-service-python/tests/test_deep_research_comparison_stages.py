from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.comparison_stage_inputs import prepare
from services.deep_research.comparison_stage_generation import generate, recorded_response
from services.deep_research.contracts import BudgetExhaustedError, DeepResearchError, digest
from services.deep_research.shared_strings import unpack
from services.deep_research.nested_tables import unpack as untables
from test_deep_research_comparison_wire import fixture as wire_fixture
from test_deep_research_comparison_layout import QUESTION
from test_deep_research_comparison_intent import record


def fixture():
    plan,_,_=wire_fixture()
    r=record()
    r.update(runId='stage-r',taskId='stage-t',idempotencyKey='stage-k',status='running',
             startedAt=None,question=QUESTION)
    r['budget'].update(maxModelCalls=18,modelCalls=0,reservedModelCalls=0,
                       maxTokens=100000,tokens=0,normalTokens=0,maxWallClockSeconds=360,elapsedSeconds=0)
    r['state']={'outputKind':'paper_comparison'}
    rows=list(plan['evidence'].values())
    aliases={row['evidenceId']:'original-'+row['evidenceId'] for row in rows}
    bundles=[{'obligationId':o['obligationId'],'criterionId':'c','requirement':o['question'],
              'evidenceIds':[aliases[row['evidenceId']]],'source':row['source']}
             for o in plan['requirements'] for row in rows]
    return r,plan,rows,aliases,bundles


def prepared():
    r,p,rows,aliases,bundles=fixture()
    return r,prepare(r,p['requirements'],p['sources'],rows,{},bundles,aliases,merge_joint=False)


def test_joint_fps_stage_reuses_fulltext_setup_under_row_cap():
    r, plan, rows, aliases, bundles = fixture()
    r.update(comparisonPlanningContractVersion=6, comparisonReviewBatchContractVersion=2,
             comparisonAuthoringContractVersion=16, comparisonJointReportsContractVersion=3)
    goal = next(row for row in plan['requirements'] if row['comparisonRole']['kind'] == 'joint')
    goal['question'] = '为什么不能直接拿两篇的FPS排名？'
    template = {**rows[0], 'accessLevel': 'fulltext', 'sourceContext': {}}
    template.pop('tableData', None)
    template.pop('tableDataRef', None)
    additions = [
        {**template, 'evidenceId': f'optional-{index}', 'quote': f'Additional description {index}.'}
        for index in range(22)
    ]
    note = {**template, 'evidenceId': 'evaluation-setup',
            'quote': 'All performance evaluations are conducted on an A6000 GPU.'}
    rows.extend([*additions, note])
    aliases.update({row['evidenceId']: 'original-' + row['evidenceId'] for row in [*additions, note]})
    versions = [prepare({**r, 'comparisonJointReportsContractVersion': version}, plan['requirements'],
                        plan['sources'], rows, {}, bundles, aliases) for version in (3, 4)]
    prior, current = [next(s for s in snap['stages'] if s['stageId'] == 'joint') for snap in versions]
    assert prior['requiredEvidenceIds'] == current['requiredEvidenceIds']
    assert len(current['suppliedEvidenceIds']) <= 20
    assert note['evidenceId'] not in prior['suppliedEvidenceIds']
    assert note['evidenceId'] in current['allowedEvidenceByTarget']['joint_' + goal['obligationId']]
    assert note['quote'] in current['prompt']


def test_complete_joint_merge_reduces_calls_without_dropping_targets_or_premise_bundles():
    r,p,rows,aliases,bundles=fixture()
    snapshot=prepare(r,p['requirements'],p['sources'],rows,{},bundles,aliases)
    assert len(snapshot['stages'])==2
    assert sum(s['requiredBundleCount'] for s in snapshot['stages'])==len(bundles)
    ids=[target for stage in snapshot['stages'] for target in stage['targetIds']]
    assert len(ids)==len(set(ids))==10
    merged=next(s for s in snapshot['stages'] if s['stageId'].endswith('_joint'))
    data=packet(merged)
    assert data['jointTargets'] and sum(bool(p['targets']) for p in data['papers'])==1
    assert all(set(t['evidenceIds'])<=set(merged['suppliedEvidenceIds'])
               for paper in data['papers'] for t in paper['targets'])
    assert snapshot['admission']['callLowerBound']==10


def test_atomic_exploration_preserves_the_full_plan_call_floor(tmp_path):
    from services.deep_research.comparison_stage_inputs import exploration_completion_calls
    from services.deep_research.repository import DeepResearchRepository

    record, plan, rows, aliases, bundles = fixture()
    record.update(comparisonPlanningContractVersion=6, comparisonReviewBatchContractVersion=2,
                  comparisonAuthoringContractVersion=16, comparisonJointReportsContractVersion=9,
                  comparisonExplorationContractVersion=1, materials=list(plan['sources'].values()))
    record['state']['plan'] = [{'obligations': plan['requirements']}]
    allotted = prepare(record, plan['requirements'], plan['sources'], rows, {}, bundles, aliases)
    floor = allotted['admission']['callLowerBound']
    assert floor == exploration_completion_calls(record)
    assert exploration_completion_calls({**record, 'comparisonExplorationContractVersion': True}) == 0
    maximum = record['budget']['maxModelCalls']
    record['budget']['modelCalls'] = maximum - floor - 1
    repo = DeepResearchRepository(str(tmp_path/'comparison.sqlite3'))
    repo.initialize()
    repo.create_run(record)
    run_id = record['runId']
    reserve = dict(run_id=run_id, node='assess_relevance', tool='llm_invoke',
                   budget_delta={'modelCalls':1,'tokens':100})
    repo.reserve_call(**reserve, args_digest='last-admitted-assessment')
    before = repo.require_run(run_id)
    assert before['budget']['modelCalls'] == maximum - floor
    with pytest.raises(BudgetExhaustedError) as error:
        repo.reserve_call(**reserve, args_digest='would-consume-generation-budget')
    assert error.value.details == {'kind':'comparisonExplorationCalls',
                                   'limit':maximum-floor,'used':maximum-floor+1}
    assert repo.require_run(run_id) == before
    with pytest.raises(ValueError, match='Immutable'):
        repo.update_run(run_id, lambda current: {**current, 'comparisonExplorationContractVersion':0})
    reserve['node'] = 'synthesize'
    repo.reserve_call(**reserve, args_digest='generation-can-use-its-capacity')


def packet(stage):
    text=stage['prompt'].split('Exact question obligations, source permissions, unchanged quotations/context, and visible typed cells:\n',1)[1]
    data=json.JSONDecoder().raw_decode(text)[0]
    return untables(unpack(data)) if set(data)=={'strings','value'} else data


def test_benchmark_owner_is_literal_in_new_joint_stage_and_old_packet_still_decodes():
    from services.deep_research.comparison_joint_reports import preserve_requested_numeric_example

    r, plan, rows, aliases, bundles = fixture()
    r.update(comparisonPlanningContractVersion=6, comparisonReviewBatchContractVersion=2,
             comparisonAuthoringContractVersion=16)
    r['question'] += '数字只选一组来源明确的同口径基线对照。'
    plan_items = preserve_requested_numeric_example([{'obligations': plan['requirements']}], r['question'])
    requirements = [goal for item in plan_items for goal in item['obligations']]
    result = [prepare({**r, 'comparisonJointReportsContractVersion': version}, requirements,
                      plan['sources'], rows, {}, bundles, aliases) for version in (6, 7, 8)]
    old, literal, compact = [next(s for s in value['stages'] if s['stageId'] == 'joint') for value in result]
    target = 'joint_requested_numeric_example_matched_example'
    marker = 'Exact question obligations, source permissions, unchanged quotations/context, and visible typed cells:\n'
    old_wire = json.JSONDecoder().raw_decode(old['prompt'].split(marker, 1)[1])[0]
    assert target in old_wire['strings']
    for current in (literal, compact):
        assert f'"targetId":"{target}"' in current['prompt']
        assert f'"benchmarkExampleOwner":"{target}"' in current['prompt']
        assert packet(old) == packet(current)
        assert old['allowedEvidenceByTarget'] == current['allowedEvidenceByTarget']
        assert old['allowedCellsByTarget'] == current['allowedCellsByTarget']
    assert compact['inputBytes'] < literal['inputBytes']
    for prior, current in zip(result[1]['stages'], result[2]['stages'], strict=True):
        if prior['stageId'] != 'joint':
            assert prior == current


def null_response(stage):
    return {'content':json.dumps({'answers':[{'targetId':key,'goalRefs':[],'point':None}
                                           for key in stage['targetIds']]}),'finishReason':'stop'}


def test_stage_table_choices_exclude_unmatched_baseline_and_reserved_benchmark_cells():
    from services.deep_research.comparison_wire import stage_table_catalog

    original = [{
        'evidenceId': 'E1', 'source': 'P1', 'matchedProtocol': {'rowNumber': 2, 'noteEvidenceId': 'E2'},
        'groups': [['Room', ['FPS', 'Training time']]],
        'rows': [[1, 'Baseline [1]', [['V1', '10'], ['V2', '20']]],
                 [2, 'Baseline * [1]', [['V3', '11'], ['V4', '20']]],
                 [3, 'Ours', [['V5', '21'], ['V6', '30']]]],
    }]
    frozen = deepcopy(original)
    joint, = stage_table_catalog(original, joint=True, reserved_benchmark=True)
    assert joint['rows'] == original[0]['rows'][1:]
    assert joint['matchedProtocol'] == frozen[0]['matchedProtocol']
    paper, = stage_table_catalog(original, joint=False, reserved_benchmark=True)
    assert paper['groups'] == [['Room', ['Training time']]]
    assert [row[2] for row in paper['rows']] == [[['V2', '20']], [['V4', '20']], [['V6', '30']]]
    assert original == frozen
    without_note = {key: value for key, value in original[0].items() if key != 'matchedProtocol'}
    assert not stage_table_catalog([without_note], joint=True, reserved_benchmark=True,
                                   known_protocols={'E1': original[0]['matchedProtocol']})
    assert not stage_table_catalog([without_note], joint=True, reserved_benchmark=True,
                                   known_protocols={})
    assert stage_table_catalog(original, joint=True, reserved_benchmark=True,
                               known_protocols={'E1': original[0]['matchedProtocol']}) == [joint]


def test_table_and_note_get_a_joint_fit_before_individual_optional_rows():
    from services.deep_research.synthesis_evidence import fit_premises

    rows = [{'evidenceId': name, 'quote': quote}
            for name, quote in [('required', '1'), ('other', '1234'), ('note', '12'), ('table', '123')]]
    render = lambda selection: ''.join(row['quote'] for row in selection)
    required = [{'evidenceIds': ['required']}]
    def selected(limit):
        _, fit, missing = fit_premises(rows, render, required, max_bytes=limit,
                                       optional_bundles=[('note', 'table')])
        assert not missing
        return [row['evidenceId'] for row in fit]
    assert selected(6) == ['required', 'note', 'table']
    assert selected(5) == ['required', 'other']


def test_local_contributions_keep_global_goals_but_do_not_assign_peer_questions_to_paper():
    r, p, rows, aliases, bundles = fixture()
    r.update(comparisonPlanningContractVersion=6, comparisonReviewBatchContractVersion=2,
             comparisonAuthoringContractVersion=3)
    before = deepcopy((p, rows, bundles))
    snapshot = prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases)
    assert [s['stageId'] for s in snapshot['stages']] == ['P1', 'P2', 'joint']
    assert snapshot['requirements'] == p['requirements']
    assert sum(s['requiredBundleCount'] for s in snapshot['stages']) == len(bundles)
    for stage in snapshot['stages']:
        data = packet(stage)
        assert 'requirements' not in data
        goals = data['requestContext']['researchGoals']
        assert [{k: v for k, v in row.items() if k != 'goalRef'} for row in goals] == [
            {k: v for k, v in row.items() if k != 'obligationId'} for row in p['requirements']]
        assert data['requestContext']['question'] == r['question']
        assert 'complete questions' not in stage['prompt']
        assert 'The assembled report must answer all human goals' in stage['prompt']
        for paper in data['papers']:
            for target in paper['targets']:
                assert target['contribution'] == {'source': paper['source'],
                    'dimension': target['question'], 'scope': 'own_paper_only'}
                assert all(set(choice) == {'goalRef'} for choice in target['goalChoices'])
        if stage['stageId'] == 'joint':
            assert data['jointTargets']
            assert all(t['goalChoices'][0]['question'] for t in data['jointTargets'])
    assert (p, rows, bundles) == before


def test_previous_isolated_profile_retains_full_goal_questions_and_original_identity():
    r, p, rows, aliases, bundles = fixture()
    r.update(comparisonPlanningContractVersion=6, comparisonReviewBatchContractVersion=2,
             comparisonAuthoringContractVersion=2)
    old = prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases)
    assert all('requirements' in packet(stage) for stage in old['stages'])
    assert all('researchGoals' not in packet(stage)['requestContext'] for stage in old['stages'])
    assert all('complete questions' in stage['prompt'] for stage in old['stages'])
    assert prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases) == old
    r['state']['comparisonStageInput'] = old
    r['comparisonAuthoringContractVersion'] = 3
    with pytest.raises(DeepResearchError, match='身份改变'):
        prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases)


def test_single_paper_packet_excludes_peer_assignments_but_keeps_joint_request():
    r, p, rows, aliases, bundles = fixture()
    r.update(question=QUESTION + '向初学者解释。',
             comparisonPlanningContractVersion=6, comparisonReviewBatchContractVersion=2,
             comparisonAuthoringContractVersion=10)
    previous = prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases)
    r['comparisonAuthoringContractVersion'] = 11
    current = prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases)

    assert current['requirements'] == previous['requirements'] == p['requirements']
    assert current['stages'][-1] == previous['stages'][-1]
    for old, new in zip(previous['stages'][:-1], current['stages'][:-1], strict=True):
        data = packet(new)
        assert data['requestContext'] == {'audience': 'beginner'}
        assert data['jointTargets'] == []
        assert data['papers'] == packet(old)['papers']
        assert r['question'] not in new['prompt']
        assert 'whether their text is available' in new['prompt']
        for field in ('targetIds', 'requiredEvidenceIds', 'allowedEvidenceByTarget', 'allowedCellsByTarget'):
            assert old[field] == new[field]


def test_explicit_one_benchmark_example_is_assigned_to_joint_output():
    r, p, rows, aliases, bundles = fixture()
    limit = '数字只选一组来源和口径明确的基线对照作例子'
    r.update(question=QUESTION + '。' + limit, comparisonPlanningContractVersion=6,
             comparisonReviewBatchContractVersion=2, comparisonAuthoringContractVersion=11)
    joint = next(o for o in p['requirements'] if o['comparisonRole']['kind'] == 'joint')
    joint['comparisonRole']['requestExcerpt'] = limit
    snapshot = prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases)
    for stage in snapshot['stages'][:-1]:
        assert packet(stage)['requestContext']['numericExample'] == 'one joint example for the entire report'
        assert 'Do not repeat benchmark metric values' in stage['prompt'].replace('\n', '')
    assert limit in packet(snapshot['stages'][-1])['requestContext']['question']
    assert 'numericExample' not in packet(snapshot['stages'][-1])['requestContext']


def test_joint_stage_prioritizes_typed_table_when_literal_anchor_only_names_advice():
    r, p, rows, aliases, bundles = fixture()
    r.update(question=QUESTION + '。数字只选一组来源和口径明确的基线对照作例子',
             comparisonPlanningContractVersion=6, comparisonReviewBatchContractVersion=2,
             comparisonAuthoringContractVersion=12)
    joint = next(o for o in p['requirements'] if o['comparisonRole']['kind'] == 'joint')
    joint['question'] += '，给出一组数字示例。'
    table = rows[0]
    text = {k: v for k, v in table.items() if k != 'tableData'}
    text.update(evidenceId='E99', quote='Supplemental discussion without a typed result table. ' * 40)
    rows.insert(0, text)
    aliases['E99'] = 'original-E99'
    bundles = [b for b in bundles if 'original-' + table['evidenceId'] not in b['evidenceIds']]
    historical = prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases)
    r['comparisonAuthoringContractVersion'] = 13
    current = prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases)
    old_joint, new_joint = historical['stages'][-1], current['stages'][-1]
    assert old_joint['requiredEvidenceIds'] == new_joint['requiredEvidenceIds']
    assert old_joint['suppliedEvidenceIds'].index('E99') < old_joint['suppliedEvidenceIds'].index(table['evidenceId'])
    assert new_joint['suppliedEvidenceIds'].index(table['evidenceId']) < new_joint['suppliedEvidenceIds'].index('E99')
    assert all('numericExample' in packet(stage)['requestContext'] for stage in current['stages'][:-1])


def test_explicit_benchmark_example_restricts_table_output_without_hiding_evidence():
    r, plan, rows, aliases, bundles = fixture()
    r.update(question=QUESTION + '。数字只选一组明确的基线对照作例子',
             comparisonPlanningContractVersion=6, comparisonReviewBatchContractVersion=2,
             comparisonAuthoringContractVersion=16)
    goal = next(o for o in plan['requirements'] if o['comparisonRole']['kind'] == 'joint')
    goal['question'] += '，给出一组数字示例和显存受限建议。'
    goal['completionCriteria'] = [
        {'criterionId': 'example', 'requirement': '给出一组同口径的数字对照。', 'responseType': 'identification'},
        {'criterionId': 'advice', 'requirement': '给出显存受限的条件建议。', 'responseType': 'explanation'},
    ]
    legacy, updated = [
        prepare({**r, 'comparisonJointReportsContractVersion': version}, plan['requirements'],
                plan['sources'], rows, {}, bundles, aliases) for version in (4, 5)
    ]
    owner = 'joint_' + goal['obligationId'] + '_matched_example'
    for old_stage, stage in zip(legacy['stages'], updated['stages'], strict=True):
        assert stage['requiredEvidenceIds'] == old_stage['requiredEvidenceIds']
        data = packet(stage)
        assert data['requestContext']['benchmarkExampleOwner'] == owner
        tables = [table for paper in data['papers'] for table in paper['tableCatalog']]
        assert tables
        fps_refs = {ref for table in tables for _, _, cells in table['rows'] for ref, _ in cells[::2]}
        train_refs = {ref for table in tables for _, _, cells in table['rows'] for ref, _ in cells[1::2]}
        for target, refs in stage['allowedCellsByTarget'].items():
            if target == owner:
                assert fps_refs.intersection(refs)
            else:
                assert not fps_refs.intersection(refs)
                assert train_refs.intersection(refs)
                assert fps_refs.intersection(old_stage['allowedCellsByTarget'][target])


def test_mixed_joint_goal_gets_two_wire_targets_under_original_obligation():
    r, p, rows, aliases, bundles = fixture()
    r.update(question=QUESTION + '。数字只选一组明确的基线对照作例子',
             comparisonPlanningContractVersion=6, comparisonReviewBatchContractVersion=2,
             comparisonAuthoringContractVersion=14)
    goal = next(o for o in p['requirements'] if o['comparisonRole']['kind'] == 'joint')
    goal['question'] += '，给出一组数字示例和显存受限建议。'
    goal['completionCriteria'] = [
        {'criterionId':'example','requirement':'给出一组同口径的数字对照。','responseType':'identification'},
        {'criterionId':'advice','requirement':'给出显存受限的条件建议。','responseType':'explanation'},
    ]
    current = prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases)
    assert current['requirements'] == p['requirements']
    joint = current['stages'][-1]
    parts = [target for target in packet(joint)['jointTargets'] if 'deliverable' in target]
    assert [x['deliverable'] for x in parts] == ['matched_example','conditional_advice']
    assert parts[0]['targetId'] != parts[1]['targetId'] and parts[0]['goalChoices'] == parts[1]['goalChoices']
    assert len(joint['targetIds']) == 3 and joint['maxPoints'] == 3


def test_compact_stage_policy_preserves_the_full_packet_and_request_checkpoint():
    r, p, rows, aliases, bundles = fixture()
    r.update(comparisonPlanningContractVersion=6, comparisonReviewBatchContractVersion=2,
             comparisonAuthoringContractVersion=6)

    def build():
        return prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases)

    historical = build()
    r['comparisonAuthoringContractVersion'] = 7
    compact = build()
    for old, new in zip(historical['stages'], compact['stages'], strict=True):
        assert packet(old) == packet(new)
        assert new['inputBytes'] < old['inputBytes'] - 1000
        for key in ('targetIds', 'requiredEvidenceIds', 'allowedEvidenceByTarget', 'allowedCellsByTarget'):
            assert new[key] == old[key]
    r['state']['comparisonStageInput'] = compact
    assert build() == compact
    r['comparisonAuthoringContractVersion'] = 6
    with pytest.raises(DeepResearchError, match='身份改变'):
        build()


def test_preparation_keeps_each_bundle_once_source_local_with_typed_tables_and_no_approval():
    r,p,rows,aliases,bundles=fixture();before=deepcopy((r,p,rows,aliases,bundles))
    snapshot=prepare(r,p['requirements'],p['sources'],rows,{},bundles,aliases,merge_joint=False)
    assert [s['stageId'] for s in snapshot['stages']]==['P1','P2','joint']
    assert sum(s['requiredBundleCount'] for s in snapshot['stages'])==len(bundles)
    assert snapshot['requirements']==p['requirements'] and not snapshot['scientificApproval']
    for stage in snapshot['stages']:
        data=packet(stage)
        assert data['requirements'] and stage['inputBytes']<=32000
        assert all(e['quote']==p['evidence'][e['evidenceId']]['quote'] for source in data['papers'] for e in source['evidence'])
        assert all(source['tableCatalog'] for source in data['papers'])
        if stage['stageId']!='joint':
            assert len(data['papers'])==1 and data['papers'][0]['source']==stage['stageId'] and not data['jointTargets']
            assert all(set(t['evidenceIds'])<=set(stage['suppliedEvidenceIds']) for t in data['papers'][0]['targets'])
        else:
            assert data['jointTargets'] and not any(source['targets'] for source in data['papers'])
    assert (r,p,rows,aliases,bundles)==before


def test_new_authoring_projects_task_but_preserves_full_question_and_freezes_profile():
    r, p, rows, aliases, bundles = fixture()
    r.update(comparisonPlanningContractVersion=6, comparisonReviewBatchContractVersion=2)
    old = prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases)
    assert all('Answer the human question in clear Chinese:' in s['prompt'] for s in old['stages'])
    r['comparisonAuthoringContractVersion'] = 1
    new = prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases)
    for stage in new['stages']:
        assert 'Complete ONLY the supplied paper targets' in stage['prompt']
        assert 'Answer the human question in clear Chinese:' not in stage['prompt']
        assert packet(stage)['requestContext']['question'] == r['question']
        assert packet(stage)['requestContext']['instructionLayers'] == [r['question']]
        assert stage['inputBytes'] <= 32000
    assert new['requirements'] == old['requirements']
    assert new['inputDigest'] != old['inputDigest']
    r['state']['comparisonStageInput'] = old
    with pytest.raises(DeepResearchError, match='身份改变'):
        prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases)


def test_isolated_profile_keeps_paper_and_joint_evidence_physically_separate():
    r, p, rows, aliases, bundles = fixture()
    r.update(comparisonPlanningContractVersion=6, comparisonReviewBatchContractVersion=2,
             comparisonAuthoringContractVersion=2)
    saved = prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases)
    assert [s['stageId'] for s in saved['stages']] == ['P1', 'P2', 'joint']
    assert saved['maxInputBytes'] == 24000
    assert sum(s['requiredBundleCount'] for s in saved['stages']) == len(bundles)
    assert saved['allFrozenPremiseBundlesRetained'] and saved['admission']['callLowerBound'] == 11
    for stage in saved['stages']:
        data = packet(stage)
        assert stage['inputBytes'] <= 24000
        assert '"subject":"method","attribute":"setting","value":"exact observed value"' in stage['prompt']
        if stage['stageId'] == 'joint':
            assert data['jointTargets'] and not any(p['targets'] for p in data['papers'])
        else:
            assert len(data['papers']) == 1 and not data['jointTargets']
            assert data['papers'][0]['source'] == stage['stageId']
    r['state']['comparisonStageInput'] = saved
    r['budget']['modelCalls'] = 15
    assert prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases) == saved
    r['comparisonAuthoringContractVersion'] = 1
    with pytest.raises(DeepResearchError, match='身份改变'):
        prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases)


def test_isolated_profile_refuses_missing_mandatory_context_instead_of_remerging():
    r, p, rows, aliases, bundles = fixture()
    r.update(comparisonPlanningContractVersion=6, comparisonReviewBatchContractVersion=2,
             comparisonAuthoringContractVersion=2)
    bundles[0]['requiredContextByEvidenceId'] = {bundles[0]['evidenceIds'][0]: 'required context ' * 10000}
    with pytest.raises((DeepResearchError, ValueError)):
        prepare(r, p['requirements'], p['sources'], rows, {}, bundles, aliases)


@pytest.mark.parametrize('profile', [None, 0, 1, 2])
def test_repository_never_upgrades_or_relabels_comparison_authoring_on_existing_run(tmp_path, profile):
    r, repo = graph_fixture(tmp_path, authoring=profile)
    before = repo.require_run(r['runId'])
    replacement = 1 if profile == 2 else 2
    with pytest.raises(ValueError, match='Immutable run field'):
        repo.update_run(r['runId'], lambda value: {**value, 'comparisonAuthoringContractVersion': replacement})
    with pytest.raises(ValueError, match='Immutable run field'):
        repo.update_run(r['runId'], lambda value: {**value, 'comparisonAuthoringContractVersion': True})
    assert repo.require_run(r['runId']) == before


def test_actual_graph_persists_exact_measurement_conditions_without_semantic_approval(tmp_path):
    from services.deep_research.graph import make_synthesize_node
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.verification import verify_claims
    r, repo = graph_fixture(tmp_path, authoring=1)
    def seed(row):
        for ev in row['state']['evidence']:
            ev.update(quote='Table row 8: Ours | 134', sourceContext='Table row 8: Ours | 134',
                tableData={'groups': [['Benchmark', ['FPS']]], 'rows': [[8, 'Ours', ['134']]]})
        return row
    repo.update_run(r['runId'], seed)
    raw = []
    def invoke(rid, node, prompt, options, **kw):
        data = packet({'prompt': prompt})
        response = json.loads(graph_response(prompt)['content'])
        target = next(a for a in response['answers'] if a['point'] is not None)
        paper = next(p for p in data['papers'] if p['targets'])
        catalog = paper['tableCatalog'][0]
        target['point']['body']['prose']['text'] = '该方法在此组评测中报告渲染速度。'
        target['point']['cellRefs'] = [catalog['rows'][0][2][0][0]]
        target['point']['evidenceRefs'] = [catalog['evidenceId']]
        raw.append(deepcopy(response))
        return {'content': json.dumps(response), 'finishReason': 'stop'}
    update = lambda rid, fn, **kw: repo.update_run(rid, fn, **kw)
    make_synthesize_node(invoke, update, scope_validator=lambda *_: True)({'run_id': r['runId']})
    reopened = DeepResearchRepository(tmp_path / 'graph.sqlite3')
    reopened.initialize()
    saved = reopened.require_run(r['runId'])['state']
    claims = saved['reportBody']['claims']
    assert len(claims) == 2
    assert all(c['conditions']['原表测量'] == 'Benchmark / Ours：FPS 134' for c in claims)
    assert all(not a['point']['body']['prose']['conditions'] for payload in raw
               for a in payload['answers'] if a['point'] is not None)
    assert not verify_claims(claims, saved['evidence'], Mock(return_value=[]))['accepted']


@pytest.mark.parametrize('mutation',['missing','mixed_owner','unknown_goal','capacity'])
def test_incomplete_evidence_or_mixed_source_bundle_stops_before_generation(mutation):
    r,p,rows,aliases,bundles=fixture()
    if mutation=='missing':bundles[0]['evidenceIds']=['unknown']
    elif mutation=='mixed_owner':bundles[0]['evidenceIds']=list(aliases.values())
    elif mutation=='unknown_goal':bundles[0]['obligationId']='foreign'
    else:rows[0]['quote']='required complete quotation '*10000
    with pytest.raises((DeepResearchError,ValueError)):
        prepare(r,p['requirements'],p['sources'],rows,{},bundles,aliases,merge_joint=False)


def test_initial_call_floor_and_recovery_use_stable_inputs_not_changed_ledger_counts():
    r,p,rows,aliases,bundles=fixture()
    snapshot=prepare(r,p['requirements'],p['sources'],rows,{},bundles,aliases,merge_joint=False)
    assert snapshot['admission']['providerTokensAndWallClockFitEstablished'] is False
    r['budget']['modelCalls']=10
    with pytest.raises(BudgetExhaustedError):prepare(r,p['requirements'],p['sources'],rows,{},bundles,aliases,merge_joint=False)
    r['state']['comparisonStageInput']=snapshot
    assert prepare(r,p['requirements'],p['sources'],rows,{},bundles,aliases,merge_joint=False)==snapshot
    rows[0]['quote']+=' changed'
    with pytest.raises(DeepResearchError,match='改变'):
        prepare(r,p['requirements'],p['sources'],rows,{},bundles,aliases,merge_joint=False)


def test_received_stages_survive_real_sqlite_reopen_without_any_new_dispatch(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    r,snapshot=prepared()
    path=tmp_path/'stages.sqlite3';repo=DeepResearchRepository(path);repo.initialize();repo.create_run(r)
    def current():return repo.require_run(r['runId'])
    def checkpoint(value):
        repo.update_run(r['runId'],lambda run:{**run,'state':{**run['state'],'comparisonStageGeneration':value}})
    sent=[]
    def invoke(node,prompt,options):
        stage=next(s for s in snapshot['stages'] if s['prompt']==prompt);sent.append(stage['stageId'])
        assert node=='synthesize' and options['max_tokens']==4000
        return null_response(stage)
    response=generate(snapshot,current=current,checkpoint=checkpoint,invoke=invoke)
    assert sent==['P1','P2','joint'] and len(json.loads(response['content'])['answers'])==10
    repo=DeepResearchRepository(path);repo.initialize();blocked=Mock(side_effect=AssertionError('Unexpected dispatch'))
    assert generate(snapshot,current=current,checkpoint=checkpoint,invoke=blocked)==response
    blocked.assert_not_called()
    assert not current()['state'].get('verifiedReport')


def test_unknown_stage_never_resends_and_exact_readonly_recovery_can_continue():
    r,snapshot=prepared();sent=[]
    def current():return deepcopy(r)
    def checkpoint(value):r['state']['comparisonStageGeneration']=deepcopy(value)
    def invoke(node,prompt,options):
        stage=next(s for s in snapshot['stages'] if s['prompt']==prompt);sent.append(stage['stageId'])
        if stage['stageId']=='P2':raise TimeoutError('Unknown request')
        return null_response(stage)
    with pytest.raises(TimeoutError):generate(snapshot,current=current,checkpoint=checkpoint,invoke=invoke)
    assert sent==['P1','P2']
    blocked=Mock(side_effect=AssertionError('Must not resend an uncertain stage'))
    with pytest.raises(DeepResearchError):generate(snapshot,current=current,checkpoint=checkpoint,invoke=blocked)
    blocked.assert_not_called()
    after=Mock(return_value=null_response(snapshot['stages'][2]))
    response=generate(snapshot,current=current,checkpoint=checkpoint,invoke=after,
                      recover=lambda prompt,options:null_response(snapshot['stages'][1]))
    assert after.call_count==1 and after.call_args.args[1]==snapshot['stages'][2]['prompt']
    assert len(json.loads(response['content'])['answers'])==10


@pytest.mark.parametrize('mutation',['foreign_target','duplicate','truncated','malformed'])
def test_invalid_stage_response_is_durable_and_never_retried(mutation):
    r,snapshot=prepared()
    def current():return deepcopy(r)
    def checkpoint(value):r['state']['comparisonStageGeneration']=deepcopy(value)
    response=null_response(snapshot['stages'][0]);body=json.loads(response['content'])
    if mutation=='foreign_target':body['answers'][0]['targetId']=snapshot['stages'][1]['targetIds'][0]
    elif mutation=='duplicate':body['answers'].append(deepcopy(body['answers'][0]))
    elif mutation=='truncated':response['finishReason']='length'
    else:body={'items':[]}
    response['content']=json.dumps(body)
    with pytest.raises(DeepResearchError):
        generate(snapshot,current=current,checkpoint=checkpoint,invoke=Mock(return_value=response))
    blocked=Mock()
    with pytest.raises(DeepResearchError):generate(snapshot,current=current,checkpoint=checkpoint,invoke=blocked)
    blocked.assert_not_called()
    assert r['state']['comparisonStageGeneration']['stages']['P1']['status']=='invalid_response'


def test_cancel_between_stages_preserves_received_output_without_next_request():
    r,snapshot=prepared();sent=[]
    def current():return deepcopy(r)
    def checkpoint(value):r['state']['comparisonStageGeneration']=deepcopy(value)
    def invoke(node,prompt,options):
        sent.append(prompt);r['status']='stopping';return null_response(snapshot['stages'][0])
    with pytest.raises(DeepResearchError):generate(snapshot,current=current,checkpoint=checkpoint,invoke=invoke)
    assert len(sent)==1 and r['state']['comparisonStageGeneration']['stages']['P1']['status']=='compiled_unverified'


@pytest.mark.parametrize('foreign',['evidence','table'])
def test_stage_cannot_borrow_references_from_another_stage(foreign):
    r,snapshot=prepared()
    def checkpoint(value):r['state']['comparisonStageGeneration']=deepcopy(value)
    raw=[]
    def invoke(node,prompt,options):
        stage=next(s for s in snapshot['stages'] if s['prompt']==prompt)
        response=null_response(stage)
        if stage['stageId']=='P1':
            body=json.loads(response['content'])
            body['answers'][0].update(goalRefs=['G1'],point={'kind':'reported',
                'body':{'prose':{'text':'Unverified attempted statement.','conditions':{}}},
                'evidenceRefs':['E2'] if foreign=='evidence' else ['E1'],
                'cellRefs':['foreign-cell'] if foreign=='table' else []})
            response['content']=json.dumps(body);raw.append(deepcopy(response))
        return response
    response=generate(snapshot,current=lambda:deepcopy(r),checkpoint=checkpoint,invoke=invoke)
    assert json.loads(response['content'])['answers'][0]['point'] is None
    entry=r['state']['comparisonStageGeneration']['stages']['P1']
    assert entry['response']==raw[0] and entry['isolatedTargets'][0]['reason']=='stage_'+foreign+'_permission'


@pytest.mark.parametrize('bad_field,reason', [
    ('kind', 'stage_claim_kind'),
    ('cellRefs', 'stage_table_permission'),
])
def test_explicit_stage_shape_keeps_valid_siblings_and_journals_invalid_rows(bad_field, reason):
    r, plan, rows, aliases, bundles = fixture()
    r.update(comparisonPlanningContractVersion=6, comparisonReviewBatchContractVersion=2,
             comparisonAuthoringContractVersion=8)
    snapshot = prepare(r, plan['requirements'], plan['sources'], rows, {}, bundles, aliases)
    raw = []

    def invoke(node, prompt, options):
        stage = next(item for item in snapshot['stages'] if item['prompt'] == prompt)
        response = null_response(stage)
        if stage['stageId'] != 'P1':
            return response
        assert '"kind":"reported","body":{"prose":' in prompt
        assert '"cellRefs":["V_EXAMPLE"]' in prompt
        body = json.loads(response['content'])
        for answer in body['answers'][:2]:
            target = answer['targetId']
            evidence_id = stage['allowedEvidenceByTarget'][target][0]
            answer.update(goalRefs=['G1'], point={'kind': 'reported',
                'body': {'prose': {'text': 'Unverified source report.', 'conditions': {}}},
                'evidenceRefs': [evidence_id], 'cellRefs': []})
        body['answers'][0]['point'][bad_field] = 'prose' if bad_field == 'kind' else [['V_EXAMPLE', '134']]
        response['content'] = json.dumps(body)
        raw.append(deepcopy(response))
        return response

    def checkpoint(value):
        r['state']['comparisonStageGeneration'] = deepcopy(value)

    response = generate(snapshot, current=lambda: deepcopy(r), checkpoint=checkpoint, invoke=invoke)
    rejected, retained = json.loads(response['content'])['answers'][:2]
    assert rejected['point'] is None and retained['point']['kind'] == 'reported'
    entry = r['state']['comparisonStageGeneration']['stages']['P1']
    assert entry['response'] == raw[0]
    assert entry['isolatedTargets'] == [{'targetId': rejected['targetId'], 'reason': reason}]


@pytest.mark.parametrize('exhausted',['calls','time'])
def test_exhausted_dispatch_budget_does_not_send_the_next_stage(exhausted):
    r,snapshot=prepared()
    if exhausted=='calls':r['budget']['modelCalls']=r['budget']['maxModelCalls']
    else:r['budget']['elapsedSeconds']=r['budget']['maxWallClockSeconds']
    def checkpoint(value):r['state']['comparisonStageGeneration']=deepcopy(value)
    invoke=Mock()
    with pytest.raises(BudgetExhaustedError):
        generate(snapshot,current=lambda:deepcopy(r),checkpoint=checkpoint,invoke=invoke)
    invoke.assert_not_called()


def test_readonly_ledger_lookup_requires_exact_native_request_identity():
    from services.deep_research.runtime import research_model_options
    from services.deep_research.planning_transport import options_for_record
    from services.deep_research.structured_output import enabled,messages_for_record
    r,snapshot=prepared();r['structuredOutputContractVersion']=15
    prompt=snapshot['stages'][0]['prompt'];options={'max_tokens':4000,'temperature':0.2}
    extra=research_model_options('synthesize',options)
    identity={'prompt':prompt,'extra':extra}
    if enabled(r):
        identity.update(extra=options_for_record(r,'synthesize',extra),messages=messages_for_record(r,'synthesize',prompt))
    row={'runId':r['runId'],'node':'synthesize','tool':'llm_invoke','argsDigest':digest(identity),
         'status':'succeeded','result':null_response(snapshot['stages'][0])}
    before=deepcopy(row)
    assert recorded_response(r,prompt,options,[row])==row['result'] and row==before
    assert recorded_response(r,prompt+'changed',options,[row]) is None
    assert recorded_response(r,prompt,options,[row,row]) is None
    row['status']='unknown'
    assert recorded_response(r,prompt,options,[row]) is None


def graph_fixture(tmp_path, *, authoring=None):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.verification import make_evidence
    r,p,_,_,_=fixture()
    r.update(comparisonPlanningContractVersion=6,comparisonReviewBatchContractVersion=2,
             comparisonJointReportsContractVersion=3,structuredOutputContractVersion=15)
    r['materials']=[{'materialId':owner['workId'],'title':owner['title']} for owner in p['sources'].values()]
    evidence=[]
    for alias,owner in p['sources'].items():
        quote=f"{owner['title']} removes redundant features while keeping the scene representation."
        ev=make_evidence({**owner,'contentHash':'hash-'+alias,'accessLevel':'fulltext'},quote,quote,
                         location={},obligation_ids=[o['obligationId'] for o in p['requirements']])
        evidence.append(ev)
    r['state'].update(plan=[{'itemId':'p','obligations':p['requirements']}],evidence=evidence)
    if authoring is not None:
        r['comparisonAuthoringContractVersion'] = authoring
    repo=DeepResearchRepository(tmp_path/'graph.sqlite3');repo.initialize();repo.create_run(r)
    return r,repo


def graph_response(prompt):
    value=json.JSONDecoder().raw_decode(prompt.split(
        'Exact question obligations, source permissions, unchanged quotations/context, and visible typed cells:\n',1)[1])[0]
    data=untables(unpack(value)) if set(value)=={'strings','value'} else value
    targets=[t for paper in data['papers'] for t in paper['targets']]+data['jointTargets']
    answers=[{'targetId':t['targetId'],'goalRefs':[],'point':None} for t in targets]
    paper=next(p for p in data['papers'] if p['targets']);t=paper['targets'][0];e=paper['evidence'][0]
    answers[0].update(goalRefs=[t['goalChoices'][0]['goalRef']],point={
        'kind':'reported','body':{'prose':{'text':e['quote'],'conditions':{}}},
        'evidenceRefs':[e['evidenceId']],'cellRefs':[],'detailLevel':'fulltext',
        'draftingBasis':{'premiseStatus':'established','observations':[{'evidenceId':e['evidenceId'],'quote':e['quote']}],
                         'scopeDecision':'reported_case','unresolved':''}})
    return {'content':json.dumps({'answers':answers}),'finishReason':'stop'}


@pytest.mark.parametrize('fixture_accepts_facts',[False,True])
def test_actual_staged_synthesis_uses_ordinary_verification_and_publication(tmp_path,fixture_accepts_facts):
    from services.deep_research.graph import make_synthesize_node,make_verify_node,make_publish_node
    from services.deep_research.verification import verify_claims
    r,repo=graph_fixture(tmp_path);sent=[]
    def update(rid,fn,**kwargs):return repo.update_run(rid,fn,**kwargs)
    def invoke(rid,node,prompt,options,**kwargs):
        assert node=='synthesize';sent.append(prompt);return graph_response(prompt)
    synth=make_synthesize_node(invoke,update,scope_validator=lambda *_:True)({'run_id':r['runId']})
    saved=repo.require_run(r['runId'])['state']
    assert len(sent)==2 and len(saved['reportBody']['claims'])==2 and not saved.get('verifiedReport')
    assert not saved['comparisonCellDraft']['answerWireAudit']['errors']
    assert saved['reportBody']['comparisonCells']['checkOutputShapeVersion']==1
    # Positive fixture checks plumbing only, not scientific quality. The real
    # verifier without semantic verdicts must withhold every generated fact.
    checker=(lambda cs,ev,semantic:{'accepted':deepcopy(cs),'rejected':[]}) if fixture_accepts_facts else verify_claims
    make_verify_node(checker,None,update)({'run_id':r['runId'],**synth})
    publish=Mock(return_value=({'publicationId':'fixture-publication'},True))
    make_publish_node(publish,update,scope_validator=lambda *_:True)({'run_id':r['runId'],**synth})
    payload=publish.call_args.kwargs['payload']
    assert payload['outcome']!='complete'
    assert len(payload['claims'])==(2 if fixture_accepts_facts else 0)
    blocked=Mock(side_effect=AssertionError('Received stages must not be regenerated'))
    again=make_synthesize_node(blocked,update,scope_validator=lambda *_:True)({'run_id':r['runId']})
    assert again['report_version_id']==synth['report_version_id']
    blocked.assert_not_called()


def test_actual_isolated_graph_keeps_three_stages_on_reopen_and_withholds_unverified_facts(tmp_path):
    from services.deep_research.graph import make_synthesize_node, make_verify_node, make_publish_node
    from services.deep_research.verification import verify_claims
    from services.deep_research.repository import DeepResearchRepository
    r, repo = graph_fixture(tmp_path, authoring=2)
    sent = []
    def update(rid, fn, **kw):
        return repo.update_run(rid, fn, **kw)
    def invoke(rid, node, prompt, options, **kw):
        data = packet({'prompt': prompt})
        local = [p for p in data['papers'] if p['targets']]
        targets = [t for p in local for t in p['targets']] + data['jointTargets']
        if local:
            assert len(data['papers']) == 1 and not data['jointTargets']
            ev = [local[0]['evidence'][0]]
        else:
            assert data['jointTargets'] and len(data['papers']) == 2
            ev = [p['evidence'][0] for p in data['papers']]
        rows = [{'targetId': t['targetId'], 'goalRefs': [], 'point': None} for t in targets]
        rows[0].update(goalRefs=[targets[0]['goalChoices'][0]['goalRef']], point={
            'kind': 'reported', 'body': {'prose': {'text': ' '.join(e['quote'] for e in ev), 'conditions': {}}},
            'evidenceRefs': [e['evidenceId'] for e in ev], 'cellRefs': [], 'detailLevel': 'fulltext',
            'draftingBasis': {'premiseStatus': 'established',
                'observations': [{'evidenceId': e['evidenceId'], 'quote': e['quote']} for e in ev],
                'scopeDecision': 'reported_case', 'unresolved': ''}})
        if not local:
            rows[0]['point']['kind'] = 'inference'
            rows[0]['point']['body'] = {'boundary': {
                'observedSettings': [{'subject': '论文中的方法', 'attribute': '表示', 'value': '场景表示'}],
                'notEstablished': [{'type': 'comparison_evidence', 'subjects': ['方法A', '方法B'], 'quantity': '同条件排名'}]}}
        sent.append(prompt)
        return {'content': json.dumps({'answers': rows}), 'finishReason': 'stop'}
    result = make_synthesize_node(invoke, update, scope_validator=lambda *_: True)({'run_id': r['runId']})
    saved = repo.require_run(r['runId'])['state']
    assert len(sent) == len(saved['comparisonStageGeneration']['stages']) == 3
    assert len(saved['reportBody']['claims']) == 3
    assert not saved['comparisonCellDraft']['errors']
    repo = DeepResearchRepository(tmp_path / 'graph.sqlite3')
    repo.initialize()
    blocked = Mock(side_effect=AssertionError('No stage resend'))
    again = make_synthesize_node(blocked, update, scope_validator=lambda *_: True)({'run_id': r['runId']})
    assert again['report_version_id'] == result['report_version_id']
    blocked.assert_not_called()
    make_verify_node(verify_claims, None, update)({'run_id': r['runId'], **result})
    publish = Mock(return_value=({'publicationId': 'isolated-fixture'}, True))
    make_publish_node(publish, update, scope_validator=lambda *_: True)({'run_id': r['runId'], **result})
    payload = publish.call_args.kwargs['payload']
    assert not payload['claims'] and payload['outcome'] != 'complete'


def test_real_ledger_recovers_a_received_stage_after_checkpoint_write_interruption(tmp_path):
    from services.deep_research.graph import make_synthesize_node
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.runtime import research_model_options
    from llm.provider import LLMResult,LLMUsage
    r,repo=graph_fixture(tmp_path);requests=[];interrupt=[True]
    class Client:
        def invoke(self,request):
            requests.append(request.prompt);reply=graph_response(request.prompt)
            return LLMResult(provider='fixture',model='fixture',content=reply['content'],
                             usage=LLMUsage(8,4,12),finish_reason='stop')
    tracked=TrackedLLMInvoker(Client(),repo.reserve_call,repo.complete_call,max_input_tokens=32000,
        run_record_fn=repo.require_run,call_history_fn=repo.list_calls,request_options=research_model_options)
    def update(rid,fn,**kwargs):
        value=fn(repo.require_run(rid))
        journal=value.get('state',{}).get('comparisonStageGeneration',{})
        if interrupt[0] and any(s.get('status')=='response_received' for s in journal.get('stages',{}).values()):
            interrupt[0]=False;raise RuntimeError('Simulated checkpoint write interruption')
        return repo.update_run(rid,lambda _:value,**kwargs)
    with pytest.raises(RuntimeError):
        make_synthesize_node(tracked,update,scope_validator=lambda *_:True)({'run_id':r['runId']})
    assert len(requests)==1 and repo.list_calls(r['runId'])[0]['status']=='succeeded'
    result=make_synthesize_node(tracked,update,scope_validator=lambda *_:True)({'run_id':r['runId']})
    assert 'report_version_id' in result and len(requests)==2
    assert len(repo.list_calls(r['runId']))==2 and all(c['status']=='succeeded' for c in repo.list_calls(r['runId']))


def test_scope_revocation_between_real_graph_stages_refuses_the_next_send(tmp_path):
    from services.deep_research.graph import make_synthesize_node
    r,repo=graph_fixture(tmp_path);allowed=[True];sent=[]
    def update(rid,fn,**kwargs):return repo.update_run(rid,fn,**kwargs)
    def invoke(rid,node,prompt,options,**kwargs):
        sent.append(prompt);allowed[0]=False;return graph_response(prompt)
    with pytest.raises(DeepResearchError,match='权限'):
        make_synthesize_node(invoke,update,scope_validator=lambda *_:allowed[0])({'run_id':r['runId']})
    assert len(sent)==1
    journal=repo.require_run(r['runId'])['state']['comparisonStageGeneration']['stages']
    assert len(journal)==1 and next(iter(journal.values()))['status']=='compiled_unverified'


def test_real_unknown_ledger_call_is_never_resent_on_graph_reentry(tmp_path):
    from services.deep_research.graph import make_synthesize_node
    from services.deep_research.tools import TrackedLLMInvoker
    from services.deep_research.runtime import research_model_options
    from llm.provider import LLMResult,LLMUsage
    r,repo=graph_fixture(tmp_path);requests=[]
    class Client:
        def invoke(self,request):
            requests.append(request.prompt)
            if len(requests)==2:raise TimeoutError('timed out after send')
            return LLMResult(provider='fixture',model='fixture',content=graph_response(request.prompt)['content'],
                             usage=LLMUsage(8,4,12),finish_reason='stop')
    tracked=TrackedLLMInvoker(Client(),repo.reserve_call,repo.complete_call,max_input_tokens=32000,
        run_record_fn=repo.require_run,call_history_fn=repo.list_calls,request_options=research_model_options)
    def update(rid,fn,**kwargs):return repo.update_run(rid,fn,**kwargs)
    with pytest.raises(TimeoutError):
        make_synthesize_node(tracked,update,scope_validator=lambda *_:True)({'run_id':r['runId']})
    calls=repo.list_calls(r['runId']);unknown=next(c for c in calls if c['status']=='unknown')
    assert len(calls)==2 and not unknown['settled']
    with pytest.raises(DeepResearchError):
        make_synthesize_node(tracked,update,scope_validator=lambda *_:True)({'run_id':r['runId']})
    assert len(requests)==2 and repo.get_call(unknown['callId'])==unknown


def test_new_staged_graph_requires_scope_validation_before_the_first_send(tmp_path):
    from services.deep_research.graph import make_synthesize_node
    r,repo=graph_fixture(tmp_path);invoke=Mock()
    def update(rid,fn,**kwargs):return repo.update_run(rid,fn,**kwargs)
    with pytest.raises(DeepResearchError,match='范围确认'):
        make_synthesize_node(invoke,update)({'run_id':r['runId']})
    invoke.assert_not_called()


def test_cached_stages_do_not_bypass_current_material_permission(tmp_path):
    from services.deep_research.graph import make_synthesize_node
    r,repo=graph_fixture(tmp_path)
    def update(rid,fn,**kwargs):return repo.update_run(rid,fn,**kwargs)
    make_synthesize_node(lambda rid,node,prompt,options,**kw:graph_response(prompt),update,
                         scope_validator=lambda *_:True)({'run_id':r['runId']})
    blocked=Mock()
    with pytest.raises(DeepResearchError,match='权限'):
        make_synthesize_node(blocked,update,scope_validator=lambda *_:False)({'run_id':r['runId']})
    blocked.assert_not_called()


def test_human_plan_edit_retires_stage_inputs_and_keeps_raw_journal_in_history(tmp_path):
    from services.deep_research.graph import make_synthesize_node
    from services.deep_research.plan_resume import retire_outputs
    r,repo=graph_fixture(tmp_path)
    def update(rid,fn,**kwargs):return repo.update_run(rid,fn,**kwargs)
    make_synthesize_node(lambda rid,node,prompt,options,**kw:graph_response(prompt),update,
                         scope_validator=lambda *_:True)({'run_id':r['runId']})
    state=repo.require_run(r['runId'])['state'];before=deepcopy(state)
    edited=retire_outputs(state,state['plan'],0)
    assert 'comparisonStageInput' not in edited and 'comparisonStageGeneration' not in edited
    assert 'comparisonCellDraft' not in edited and 'reportBody' not in edited
    retired=edited['planEditHistory'][-1]['retiredOutputs']
    assert retired['comparisonStageInput']==before['comparisonStageInput']
    assert retired['comparisonStageGeneration']==before['comparisonStageGeneration'] and state==before
