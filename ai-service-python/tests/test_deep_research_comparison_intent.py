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
