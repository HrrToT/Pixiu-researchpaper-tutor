from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.comparison_intent import enabled, validate_role
from services.deep_research.comparison_cells import plan_cells, compile_cells, partition_source_bound_claims
from services.deep_research.initial_plan_response import validate_shape

QUESTION='比较两篇论文的压缩机制，说明可比性并给出选择建议。'


def obligation(oid,kind,label,excerpt):
    return {'obligationId':oid,'question':label,'requiredSources':['left','right'],
            'searchQuery':label,'purpose':'supporting_research' if kind=='supporting' else 'answer_requirement',
            'requestExcerpt':'比较两篇论文的压缩机制' if kind=='per_paper' else '说明可比性并给出选择建议',
            'completionCriteria':[{'criterionId':'c','requirement':label,'responseType':'explanation'}],
            'comparisonRole':{'kind':kind,'label':label,'requestExcerpt':excerpt}}


def plan():
    return [
        {'itemId':'facts','question':'压缩机制','searchQuery':'compression mechanism',
         'dependencies':[],'priority':1,'obligations':[obligation('mechanism','per_paper','压缩机制','压缩机制')]},
        {'itemId':'judgement','question':'可比性和选择','searchQuery':'comparison conditions',
         'dependencies':['facts'],'priority':2,'obligations':[
             obligation('fairness','joint','可比性','可比性'),
             obligation('choice','joint','选择建议','选择建议')]}]


def record():
    from test_deep_research_factual_prompt import node_capture
    _,_,value=node_capture(3)
    value.update(question=QUESTION,comparisonCellsContractVersion=1,comparisonPlanningContractVersion=1,
        factualReviewContractVersion=4,authoredBodyContractVersion=3,scopeExpressionContractVersion=5,
        synthesisInputContractVersion=2,draftValidationContractVersion=1,reportPresentationContractVersion=4,
        initialPlanInstructionsContractVersion=1,initialPlanResponseContractVersion=1,
        planCompletionContractVersion=1,requestSemanticsContractVersion=2,structuredOutputContractVersion=15,
        claimIsolationContractVersion=1,materials=[{'materialId':x,'title':x} for x in ('left','right')])
    value['budget'].update(maxModelCalls=18,modelCalls=0,reservedModelCalls=0)
    return value


@pytest.mark.parametrize('field,value',[
    ('kind','unsupported'),('kind',[]),('label',''),('label','bad\nlabel'),
    ('requestExcerpt','not literal'),('requestExcerpt',None)])
def test_invalid_role_does_not_rewrite_the_obligation(field,value):
    target=plan()[0]['obligations'][0];target['comparisonRole'][field]=value;before=deepcopy(target)
    with pytest.raises(ValueError):validate_role(target,QUESTION)
    assert target==before


def test_role_shape_accepts_short_exact_axes_only_for_new_plans():
    value=plan();before=deepcopy(value)
    validate_shape(value,QUESTION,comparison_roles=True)
    assert value==before
    with pytest.raises(ValueError):validate_shape(value,QUESTION)
    target=value[0]['obligations'][0];target['purpose']='supporting_research'
    with pytest.raises(ValueError):validate_role(target,QUESTION)


def test_supporting_role_is_retained_without_becoming_a_table_or_conclusion_target():
    cp,payload=packets()
    support=obligation('context','supporting','实验条件','说明可比性')
    support['requiredSourceAliases']=['P1','P2']
    requirements=[*cp['requirements'],support]
    cp=plan_cells(requirements,cp['sources'],list(cp['evidence'].values()),
                  typed_roles=True,shared_axes=True,question=QUESTION)
    result=compile_cells(payload,cp,max_claims=5)
    assert len(cp['cells'])==2 and 'context' in result['unresolvedObligationIds']
    assert any(o['obligationId']=='context' for o in cp['requirements'])
    payload['conclusions'][0]['obligationIds']=['context']
    assert compile_cells(payload,cp,max_claims=5)['errors'][0]['reason']=='invalid_conclusion_obligations'


def test_planning_retains_explicit_numeric_example_omitted_by_model():
    from services.deep_research.graph import make_plan_node
    from services.deep_research.coverage import validate_plan
    from services.deep_research.comparison_joint_reports import preserve_requested_numeric_example, split_joint_deliverables

    current = record()
    current.update(runId='r', question=QUESTION + '数字只选一组来源明确的基线对照作例子。',
                   comparisonPlanningContractVersion=6, comparisonAuthoringContractVersion=16,
                   comparisonReviewBatchContractVersion=2)
    planned = plan()

    def update(_rid, callback, **_kw):
        nonlocal current
        current = callback(deepcopy(current))
        return deepcopy(current)

    model = Mock(return_value={'content':json.dumps({'items':planned})})
    run = make_plan_node(model, update, validate_plan)({'run_id':'r'})
    assert not run.get('error_code')
    model.assert_called_once()
    frozen = current['state']['plan']
    obligations = [o for item in frozen for o in item['obligations']]
    numeric = next(o for o in obligations if o['obligationId']=='requested_numeric_example')
    assert set(numeric['requiredSources']) == {'left','right'}
    assert numeric['requestExcerpt'] in current['question']
    assert preserve_requested_numeric_example(frozen, current['question']) is frozen
    assert preserve_requested_numeric_example(planned, QUESTION) is planned
    roles = {o['obligationId']:{**o['comparisonRole'],'question':o['question']} for o in obligations}
    categorized = split_joint_deliverables(roles, obligations, current['question'], classify_standalone=True)
    assert categorized['requested_numeric_example'][0]['kind'] == 'matched_example'
    assert categorized['choice'][0]['kind'] == 'conditional_advice'


def test_followup_reuses_parent_context_without_adding_its_numeric_example():
    from services.deep_research.comparison_joint_reports import joint_numeric_example, preserve_requested_numeric_example
    from services.deep_research.request_context import ResearchQuestion

    ask = '只解释为什么不同论文中的 FPS 不能直接相除。'
    example = '数字只选一组来源明确的基线对照作例子。'
    frozen = plan()
    joint = next(o for item in frozen for o in item['obligations'] if o['comparisonRole']['kind'] == 'joint')
    roles = {'example': {**joint['comparisonRole'], 'requestExcerpt': example, 'question': joint['question']}}
    without = ResearchQuestion(f'{ask}\n{example}', [ask, example], [ask])
    assert preserve_requested_numeric_example(frozen, without) is frozen
    assert not joint_numeric_example(roles, without)

    with_example = ResearchQuestion(f'{ask}\n{example}', [ask, example], [ask, example])
    assert any(o['obligationId'] == 'requested_numeric_example'
               for item in preserve_requested_numeric_example(frozen, with_example) for o in item['obligations'])
    assert joint_numeric_example(roles, with_example)


def test_one_example_keeps_qualitative_comparison_and_measurement_conditions():
    from services.deep_research.comparison_joint_reports import normalize_single_example_requirements
    from services.deep_research.request_context import ResearchQuestion

    axis = '存储与画质、渲染速度'
    constraint = '数字只选一组来源明确的基线对照作例子。'
    question = f'比较{axis}。{constraint}'
    original = [{'obligations': [{
        'obligationId': 'measurements',
        'question': '两篇各自报告的存储占用、画质与渲染速度是什么？',
        'comparisonRole': {'kind': 'joint', 'requestExcerpt': axis},
        'completionCriteria': [
            {'criterionId': 'metrics', 'requirement': '分别列出两篇存储、画质和渲染速度的指标。'},
            {'criterionId': 'conditions', 'requirement': '解释两篇的口径能否直接比较。'},
        ],
    }]}]
    normalized, changes = normalize_single_example_requirements(original, question)
    assert len(changes) == 2
    goal = normalized[0]['obligations'][0]
    assert all(word in goal['question'] for word in ('存储', '画质', '渲染速度', '适用条件', '一组同表同口径'))
    assert goal['completionCriteria'][0]['criterionId'] == 'metrics'
    assert goal['completionCriteria'][1] == original[0]['obligations'][0]['completionCriteria'][1]

    followup = ResearchQuestion(question, [axis, constraint], [axis])
    assert normalize_single_example_requirements(original, followup) == (original, [])
    explicit = deepcopy(original)
    explicit[0]['obligations'][0]['comparisonRole']['requestExcerpt'] = '分别列出两篇存储、画质和渲染速度的指标。'
    new_question = explicit[0]['obligations'][0]['comparisonRole']['requestExcerpt'] + constraint
    assert normalize_single_example_requirements(explicit, new_question) == (explicit, [])


@pytest.mark.parametrize('server_profile',[0,1])
def test_comparison_role_contract_is_server_selected_and_frozen(tmp_path,server_profile):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **kw:None,llm_client=object(),comparison_cells_version=server_profile)
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':QUESTION,
                            'comparisonPlanningContractVersion':1-server_profile},start_async=False)
        assert run['comparisonPlanningContractVersion']==(2 if server_profile else 0)
        for value in (None,True,1-server_profile,'1'):
            with pytest.raises(ValueError,match='Immutable'):
                repo.update_run(run['runId'],lambda r:{**r,'comparisonPlanningContractVersion':value})
    finally:facade.shutdown()


def test_full_server_planning_normalizers_preserve_roles_and_use_one_model_call(tmp_path):
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.graph import make_plan_node
    from services.deep_research.coverage import validate_plan
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **kw:None,llm_client=object(),comparison_cells_version=1)
    try:
        current,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':QUESTION},start_async=False)
        current['materials']=[{'materialId':work,'title':work} for work in ('left','right')]
        current['state']['outputKind']='paper_comparison'
        def update(rid,fn,**kwargs):
            nonlocal current
            current=fn(deepcopy(current));return deepcopy(current)
        model=Mock(return_value={'content':json.dumps({'items':plan()})})
        result=make_plan_node(model,update,validate_plan)({'run_id':current['runId']})
        assert not result.get('error_code')
        model.assert_called_once()
        roles={o['obligationId']:o['comparisonRole'] for item in current['state']['plan'] for o in item['obligations']}
        assert {oid:role['kind'] for oid,role in roles.items()}=={
            'mechanism':'per_paper','fairness':'joint','choice':'joint'}
        assert all(role['requestExcerpt'] in QUESTION for role in roles.values())
    finally:facade.shutdown()


def test_long_context_excerpt_cannot_recombine_two_typed_dimensions():
    from services.deep_research.evidence_requirements import normalize_generated_requirements
    question='比较压缩机制、训练代价，并说明可比性。'
    entries=[]
    for oid,label in [('mechanism','压缩机制'),('cost','训练代价')]:
        value=obligation(oid,'per_paper',label,label)
        value['requestExcerpt']='比较压缩机制、训练代价'
        value['completionCriteria'][0]['requirement']=label
        entries.append(value)
    value=[{'itemId':'facts','question':'分别比较机制与代价','searchQuery':'method cost',
            'obligations':entries,'dependencies':[],'priority':1}]
    result,_=normalize_generated_requirements(value,question,literal_questions=True,
        literal_imperatives=True,atomic_dimensions=True,compound_questions=True,comparison_roles=True)
    assert [o['comparisonRole']['label'] for o in result[0]['obligations']]==['压缩机制','训练代价']
    assert [o['completionCriteria'][0]['requirement'] for o in result[0]['obligations']]==['压缩机制','训练代价']
    assert all(o['requestExcerpt']=='比较压缩机制、训练代价' for o in result[0]['obligations'])


def test_joint_comparison_retains_following_explicit_requests():
    from services.deep_research.evidence_requirements import normalize_generated_requirements

    anchor = '能否直接比较两篇论文的准确率'
    internal = '论文内部的对照能支持什么'
    followup = '并给出同条件复核建议'
    excerpt = f'说明{anchor}，{internal}，{followup}'
    question = f'比较两种方法的运行时间。{excerpt}。'
    joint = obligation('limits', 'joint', '可比性', anchor)
    joint['requestExcerpt'] = excerpt
    value = [{'itemId': 'comparison', 'question': excerpt, 'obligations': [joint]}]
    options = dict(literal_questions=True, literal_imperatives=True, comparison_roles=True,
                   joint_comparison_requests=True)

    normalized, _ = normalize_generated_requirements(value, question, **options)
    criteria = normalized[0]['obligations'][0]['completionCriteria']
    assert [row['requirement'] for row in criteria] == [f'说明{anchor}', internal, followup]
    assert normalized[0]['obligations'][0]['comparisonRole']['requestExcerpt'] == anchor

    sibling = obligation('internal', 'joint', '论文内对照', internal)
    value[0]['obligations'].append(sibling)
    scoped, _ = normalize_generated_requirements(value, question, **options)
    assert [row['requirement'] for row in scoped[0]['obligations'][0]['completionCriteria']] == [f'说明{anchor}', followup]
    assert [row['requirement'] for row in scoped[0]['obligations'][1]['completionCriteria']] == [internal]


def test_per_paper_comparison_retains_two_explicit_questions_under_one_short_anchor():
    from services.deep_research.evidence_requirements import normalize_generated_requirements

    supervision = '怎样取得训练监督'
    features = '怎样产生关键点和描述子'
    excerpt = f'说明二者各自{supervision}、{features}'
    question = f'{excerpt}，并各引用一条原文结果。'
    method = obligation('method', 'per_paper', '训练与检测', supervision)
    method['requestExcerpt'] = excerpt
    value = [{'itemId': 'facts', 'question': excerpt, 'obligations': [method]}]
    opts = dict(literal_questions=True, literal_imperatives=True, atomic_dimensions=True,
                compound_questions=True, comparison_roles=True)

    original, _ = normalize_generated_requirements(value, question, **opts)
    fixed, _ = normalize_generated_requirements(value, question, **opts, per_paper_comparison_requests=True)
    assert [r['requirement'] for r in original[0]['obligations'][0]['completionCriteria']] == [supervision]
    assert [r['requirement'] for r in fixed[0]['obligations'][0]['completionCriteria']] == [
        f'说明二者各自{supervision}', features]

    value[0]['obligations'].append(obligation('features', 'per_paper', '特征产生', features))
    fixed, _ = normalize_generated_requirements(value, question, **opts, per_paper_comparison_requests=True)
    assert [r['requirement'] for r in fixed[0]['obligations'][0]['completionCriteria']] == [supervision]


def test_comparison_preserves_source_local_results_and_full_within_paper_subject():
    from services.deep_research.evidence_requirements import normalize_generated_requirements

    mechanism = '怎样提取特征'
    per_paper_result = '并各引用一条带评测条件的原文定量结果'
    source_excerpt = f'{mechanism}，{per_paper_result}'
    comparability = '能否用两篇论文的准确率直接排名'
    internal = 'Model-B 论文内部与 Model-A 的比较能支持什么'
    joint_excerpt = f'{comparability}，{internal}'
    question = f'{source_excerpt}。{joint_excerpt}。'
    method = obligation('method', 'per_paper', '特征与评测', mechanism)
    method['requestExcerpt'] = source_excerpt
    joint = obligation('comparison', 'joint', '论文内外比较', joint_excerpt)
    joint['requestExcerpt'] = joint_excerpt
    plan = [{'itemId': 'facts', 'question': question, 'obligations': [method, joint]}]

    fixed, _ = normalize_generated_requirements(plan, question, literal_questions=True, literal_imperatives=True,
        atomic_dimensions=True, compound_questions=True, comparison_roles=True, joint_comparison_requests=True,
        per_paper_comparison_requests=True, complete_comparison_clauses=True)
    method, joint = fixed[0]['obligations']
    assert [row['requirement'] for row in method['completionCriteria']] == [mechanism, per_paper_result]
    assert [row['requirement'] for row in joint['completionCriteria']] == [comparability, internal]


def packets():
    sources={f'P{i+1}':{'workId':work,'versionId':work+'-v1','title':work}
             for i,work in enumerate(('left','right','other'))}
    evidence=[{'evidenceId':f'E{i+1}','source':f'P{i+1}','obligations':['mechanism'],
               'quote':'A method under stated conditions.'} for i in range(3)]
    requirements=[deepcopy(o) for item in plan() for o in item['obligations']]
    for o in requirements:o['requiredSourceAliases']=['P1','P2']
    compiled_plan=plan_cells(requirements,sources,evidence,shared_axes=True,typed_roles=True,question=QUESTION)
    def point(ref,kind='reported'):
        return {'kind':kind,'body':{'prose':{'text':'条件明确的待核验论断。','conditions':{}}},
                'evidenceRefs':[ref],'tableBindings':[],'detailLevel':'fulltext'}
    payload={'cells':[{'cellId':c['cellId'],'claims':[point(c['evidenceIds'][0])],'unresolved':False}
                      for c in compiled_plan['cells']],
             'conclusions':[{'obligationIds':['fairness','choice'],'claim':point('E1','inference')}]}
    return compiled_plan,payload


def test_only_factual_roles_make_cells_and_joint_targets_keep_their_own_permissions():
    cp,payload=packets();assert cp['version']==3 and len(cp['cells'])==2
    assert {c['obligationId'] for c in cp['cells']}=={'mechanism'}
    result=compile_cells(payload,cp,max_claims=5)
    assert result['layoutVersion']==3 and not result['unresolvedObligationIds']
    assert {g['obligationId'] for g in result['jointGoals']}=={'fairness','choice'}
    payload['conclusions'][0]['claim']['evidenceRefs']=['E3']
    bad=compile_cells(payload,cp,max_claims=5)
    assert len(bad['report']['claims'])==2 and set(bad['unresolvedObligationIds'])=={'fairness','choice'}
    payload['conclusions'][0]['obligationIds']=['mechanism']
    bad=compile_cells(payload,cp,max_claims=5)
    assert bad['errors'][0]['reason']=='invalid_conclusion_obligations'


def test_joint_display_contract_binds_exact_public_table_without_duplicating_accepted_text():
    from services.deep_research.comparison_presentation import metadata,audit_view,audit_digest,revalidate_audit
    from services.deep_research.draft_validation import materialize_claims
    cp,payload=packets();draft=compile_cells(payload,cp,max_claims=5);draft['sources']=cp['sources']
    report,_,_=materialize_claims(draft['report'],5,authored_body=True)
    meta=metadata(draft);claims=report['claims'];view=audit_view(meta,claims)
    assert view['version']==3 and view['table']['present']
    assert '待核验论断' not in json.dumps(view,ensure_ascii=False)
    assert {g['obligationId'] for g in view['jointGoals']}=={'fairness','choice'}
    audit={'comparisonPresentationDigest':audit_digest(meta,claims),'gaps':[]}
    for target in ('text','condition','axis','joint_goal'):
        changed=deepcopy(meta);points=deepcopy(claims)
        if target=='text':points[0]['text']='Changed full accepted statement'
        elif target=='condition':points[0]['conditions']={'scope':'Different scope'}
        elif target=='axis':changed['layout'][0]['axisTitle']='Changed axis'
        else:changed['jointGoals'][0]['sourceAliases']=['P1']
        assert revalidate_audit(audit,changed,points)['status']=='invalidated_comparison_presentation'


def test_comparison_structure_cannot_be_bound_as_scientific_answer_text():
    from services.deep_research.comparison_presentation import metadata
    from services.deep_research.coverage_references import resolve_coverage_references
    from services.deep_research.draft_validation import materialize_claims
    cp,payload=packets();draft=compile_cells(payload,cp,max_claims=5);draft['sources']=cp['sources']
    report,_,_=materialize_claims(draft['report'],5,authored_body=True)
    cid=report['claims'][0]['claimId']
    resolved=resolve_coverage_references([{'obligationId':'mechanism','bindings':[
        {'claimId':cid,'field':'table'},{'claimId':cid,'field':'jointGoals'}]}],
        report['claims'],[],display_metadata=metadata(draft))
    assert all(b['referenceError']=='answer_field_not_supplied' for b in resolved[0]['bindings'])


@pytest.mark.parametrize('tamper',['foreign_source','wrong_goal','wrong_version','cell_goal','missing_joint_version'])
def test_repaired_targets_cannot_escape_joint_source_or_cell_goal_scope(tamper):
    cp,payload=packets();draft=compile_cells(payload,cp,max_claims=5);draft['sources']=cp['sources']
    claims=deepcopy(draft['report']['claims'])
    ev=[{'evidenceId':f'E{i+1}','sourceWorkId':work,'sourceVersionId':work+'-v1'}
        for i,work in enumerate(('left','right','other'))]
    if tamper=='foreign_source':claims[-1]['evidenceRefs']=['E3']
    elif tamper=='wrong_goal':claims[-1]['obligationIds']=['mechanism']
    elif tamper=='wrong_version':ev[0]['sourceVersionId']='left-v2'
    elif tamper=='missing_joint_version':
        draft['sources']['P1'].pop('versionId');ev[0].pop('sourceVersionId')
    else:claims[0]['obligationIds']=['fairness']
    good,bad=partition_source_bound_claims(claims,draft,ev)
    assert bad and len(good)<len(claims)


@pytest.mark.parametrize('include_joint',[True,False])
def test_actual_planning_generation_verification_and_publication_keep_full_goals(include_joint):
    from services.deep_research.graph import make_plan_node,make_synthesize_node,make_verify_node,make_publish_node
    from services.deep_research.coverage import validate_plan
    current=record();calls=[]
    def update(rid,fn,**kwargs):
        nonlocal current
        current=fn(deepcopy(current));return deepcopy(current)
    def invoke(rid,node,prompt,options,**kwargs):
        calls.append(node)
        if node=='plan':
            assert 'comparisonRole' in prompt
            return {'content':json.dumps({'items':plan()})}
        assert node=='synthesize' and 'Joint judgement targets' in prompt
        assert 'metric is the field name, NEVER metricKey' in prompt
        assert 'bind PSNR, not PSNR↑' in prompt
        cells=json.JSONDecoder().raw_decode(prompt.split('Cell routing and citation permissions (metadata, not evidence):\n',1)[1])[0]
        assert len(cells)==2
        def point(refs,kind='reported'):
            return {'kind':kind,'body':{'prose':{'text':'给定条件下的待核验说明。','conditions':{}}},
                    'evidenceRefs':refs,'tableBindings':[],'detailLevel':'fulltext'}
        return {'content':json.dumps({'cells':[{'cellId':c['cellId'],'claims':[point(c['evidenceIds'][:1])],
                                               'unresolved':False} for c in cells],
            'conclusions':[{'obligationIds':['fairness','choice'],
                            'claim':point([c['evidenceIds'][0] for c in cells],'inference')}] if include_joint else []})}
    result=make_plan_node(invoke,update,validate_plan)({'run_id':'r'})
    assert not result.get('error_code')
    assert all('comparisonRole' in o for item in current['state']['plan'] for o in item['obligations'])
    # Fixture evidence routing only; no independent content approval is claimed.
    for e in current['state']['evidence']:e['obligationIds']=['mechanism','fairness','choice']
    result=make_synthesize_node(invoke,update)({'run_id':'r'})
    assert not result.get('error_code')
    checker=Mock(side_effect=lambda cs,ev,semantic:{'accepted':deepcopy(cs),'rejected':[]})
    make_verify_node(checker,None,update)({'run_id':'r'})
    publish=Mock(return_value=({'publicationId':'fixture'},True))
    make_publish_node(publish,update)({'run_id':'r','report_version_id':'v'})
    payload=publish.call_args.kwargs['payload'];text=publish.call_args.kwargs['report_text']
    assert payload['comparisonCells']['version']==3 and text.count('| 压缩机制 |')==1
    assert len(payload['claims'])==(3 if include_joint else 2)
    if not include_joint:
        assert {'fairness','choice'}<=set(current['state']['comparisonCellDraft']['unresolvedObligationIds'])
    assert payload['outcome']!='complete'  # No real semantic or overall audit.
    assert calls==['plan','synthesize']
