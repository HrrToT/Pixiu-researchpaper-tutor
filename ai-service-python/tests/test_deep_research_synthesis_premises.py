from copy import deepcopy
import json
from unittest.mock import Mock
import pytest

from services.deep_research.synthesis_evidence import order_premises,fit_premises
from services.deep_research.graph import make_synthesize_node
from services.deep_research.verification import precheck_claims,verify_claims
from services.deep_research.measurement_numbers import without_dimensional_labels
from services.deep_research.factual_scope import validate_audit
from services.deep_research.tools import BudgetedSemanticChecker
from services.deep_research.audience_rewrite import rewrite_for_beginner
from services.deep_research.facade import ResearchFacade
from services.deep_research.repository import DeepResearchRepository


def evidence(eid,quote,work='p',section='Method',source='s'):
    return {'evidenceId':eid,'quote':quote,'sourceWorkId':work,'sourceVersionId':'v-'+work,
        'sourceId':source,'contentHash':'h','accessLevel':'fulltext','location':{'section':section},
        'sourceContext':quote,'verification':{'literal':'passed','semantic':'unchecked'}}


def claim(text,refs=('e',),kind='reported'):
    return {'claimId':'c','text':text,'kind':kind,'evidenceRefs':list(refs),'conditions':{},'detailLevel':'fulltext'}


def test_spatial_labels_match_existing_english_labels_but_real_dimensions_and_counts_stay_checked():
    source=[evidence('e','Our 3D Gaussian model uses a canonical space.')]
    valid=claim('三维高斯模型使用共享空间。')
    assert precheck_claims([valid],source,quantity_spelling_version=4)['rejected'][0]['reason']=='numeric_mismatch'
    assert precheck_claims([valid],source,quantity_spelling_version=5)['candidates']
    for text in ['三维高斯压缩三倍。','三维高斯运行三次。','输出三维向量。','负三维高斯模型。']:
        assert precheck_claims([claim(text)],source,quantity_spelling_version=5)['rejected'][0]['reason']=='numeric_mismatch'
    assert without_dimensional_labels('十三维特征，第三维，三维向量，负三维空间。')=='十三维特征，第三维，三维向量，负三维空间。'
    # A wrong spatial identity still needs independent semantic judgment.
    semantic=Mock(return_value=[{'claimId':'c','status':'failed','reason':'The source describes3D, not4D.'}])
    checked=verify_claims([claim('四维高斯模型。')],source,semantic,quantity_spelling_version=5)
    assert not checked['accepted'] and semantic.call_count==1
    for text,quote in [('三倍压缩。','The reported compression is 3x.'),
                       ('三点五倍压缩。','The reported compression is 3.5x.')]:
        assert precheck_claims([claim(text)],[evidence('e',quote)],quantity_spelling_version=5)['candidates']


@pytest.mark.parametrize('text',[
    '论文B的信息在提供的证据中未出现，因此无法比较。',
    '当前证据中没有论文B的信息。',
    'The provided evidence does not contain paper B inputs.',
    'The inputs are not present in the supplied evidence.'])
def test_claim_references_cannot_establish_absence_from_the_whole_pool(text):
    source=[evidence('e','Paper A uses video streams.')];candidate=claim(text,kind='inference')
    assert precheck_claims([candidate],source,absence_scope_version=6)['rejected'][0]['reason']=='absence_not_established'
    semantic=Mock(return_value=[{'claimId':'c','status':'passed'}])
    assert not verify_claims([candidate],source,semantic,absence_scope_version=6)['accepted']
    semantic.assert_not_called()


def test_positive_bounded_uncertainty_and_explicit_author_omission_keep_semantic_review():
    source=[evidence('e','We did not evaluate another dataset.')]
    assert precheck_claims([claim('作者没有评估另一个数据集。')],source,absence_scope_version=6)['candidates']
    assert precheck_claims([claim('当前证据不足以建立同条件速度排名。',kind='inference')],source,
                          absence_scope_version=6)['candidates']


def test_profiling_attribution_cannot_be_promoted_to_main_table_context():
    source=[evidence('a','Table caption: Rendering profiling on the dataset.','a','Table 7'),
            evidence('b','Tests use a fixed GPU.','b','Evaluation')]
    bad=claim('不能以各自主表FPS直接排名：A的FPS来自渲染剖析，B使用固定GPU。',('a','b'),'inference')
    assert precheck_claims([bad],source,absence_scope_version=5)['candidates']
    assert precheck_claims([bad],source,absence_scope_version=6)['rejected'][0]['reason']=='result_purpose_not_established'
    bounded=claim('这里的FPS来自渲染剖析，并非主表；这些片段不足以建立主表排名。',('a','b'),'inference')
    assert precheck_claims([bounded],source,absence_scope_version=6)['candidates']
    source.append(evidence('main','Table caption: Main results with quantitative comparison.','a','Table 1'))
    assert precheck_claims([claim('主表FPS来自定量比较。',('main',),'inference')],source,absence_scope_version=6)['candidates']


def test_whole_statement_scope_cannot_bind_only_the_true_first_clause():
    target=claim('A has a supported observation. B has an unsupported absence.');source=[evidence('e','A has an observation.')]
    audit={'claimStrength':'bounded','evidenceStrength':'bounded','supported':True,
           'statementExcerpt':'A has a supported observation.',
           'premises':[{'evidenceId':'e','quote':'A has an observation.'}]}
    assert validate_audit(target,{'scopeAudit':audit},source)==[]
    assert validate_audit(target,{'scopeAudit':audit},source,complete_statement=True)==['scope_complete_statement_not_bound']
    audit.pop('statementExcerpt');audit['statementPath']=['text']
    assert validate_audit(target,{'scopeAudit':audit},source,target_field_bindings=True,complete_statement=True)==[]
    # Binding is only a structural check, not a verdict on B's unsupported clause.


@pytest.mark.parametrize('complete',[False,True])
def test_production_checker_rejects_a_condition_only_audit_for_the_new_whole_claim_contract(complete):
    target=claim('A source-specific conclusion.',kind='inference');target['conditions']={'scope':'bounded'}
    source=[evidence('e','A source observation.')]
    verdict={'claimId':'c','status':'passed','scopeAudit':{
        'claimStrength':'bounded','evidenceStrength':'bounded','supported':True,
        'statementPath':['conditions','scope'],'premises':[{'evidenceId':'E1','path':['quote']}]}}
    invoke=Mock(return_value={'content':json.dumps([verdict])})
    result=BudgetedSemanticChecker(invoke,'r',factual_scope=True,audit_source_fields=True,
        audit_target_fields=True,complete_factual_scope=complete)([target],source)
    assert invoke.call_count==1
    assert (result[0]['status']=='failed') is complete
    if complete:
        assert 'scope_complete_statement_not_bound' in result[0]['reason']
        assert 'WHOLE assertion' in invoke.call_args.kwargs['prompt']


def test_frontier_keeps_training_stages_before_optional_table_packets_without_mutating_evidence():
    rows=[evidence('noise'+str(i),'Table row of optional numbers '+str(i),section='Table 9',source='noise') for i in range(12)]
    rows.extend([evidence('initial','We initially train the model for a fixed number of iterations.',source='training'),
                 evidence('joint','Subsequently we jointly train both components.',source='training')])
    plan=[{'obligations':[{'obligationId':'o','question':'训练模式是什么','requiredSources':['p'],
        'completionCriteria':[{'criterionId':'c','requirement':'训练是逐帧在线还是整体离线','responseType':'explanation'}]}]}]
    before=deepcopy((rows,plan));ordered,bundles=order_premises(rows,plan)
    assert {e['evidenceId'] for e in ordered[:2]}=={'initial','joint'}
    wire=[{'evidenceId':e['evidenceId'],'quote':e['quote'],'sourceContext':'Optional context'*30} for e in ordered]
    prompt,selected,missing=fit_premises(wire,lambda values:json.dumps(values,ensure_ascii=False),bundles,max_bytes=1000)
    assert {'initial','joint'}<={e['evidenceId'] for e in selected} and not missing
    assert len(prompt.encode())<=1000 and len(selected)<=20
    assert (rows,plan)==before
    tiny,kept,miss=fit_premises(wire,lambda values:json.dumps(values),bundles,max_bytes=10)
    assert kept==[] and miss and tiny=='[]'


def test_optional_table_packet_can_be_omitted_without_clipping_its_literal_quote_or_exposing_other_cells():
    rows=[{'evidenceId':'e','quote':'Table caption: Quantitative comparison.','tableDataRef':'T1'}]
    original=deepcopy(rows);bundle=[{'evidenceIds':['e']}]
    def render(values):
        tables={'T1':'numerical cell '*100} if any(v.get('tableDataRef')=='T1' for v in values) else {}
        return json.dumps({'rows':values,'tables':tables})
    _,numeric,missing=fit_premises(rows,render,bundle,max_bytes=200)
    assert numeric==[] and missing
    prompt,qualitative,missing=fit_premises(rows,render,bundle,max_bytes=200,omit_optional_table_data=True)
    assert not missing and qualitative[0]['quote']==rows[0]['quote']
    assert qualitative[0]['tableDataOmitted'] is True and 'tableDataRef' not in qualitative[0]
    assert json.loads(prompt)['tables']=={} and rows==original


def test_graph_table_packet_is_shared_only_with_its_exact_paper_version():
    packet={'groups':[['Data',['FPS']]],'rows':[[1,'Ours',['30']]]}
    rows=[evidence('a1','Table row 1: Ours | 30','a'),evidence('a2','Table caption: Results.','a'),
          evidence('b1','Table row 1: Ours | 30','b')]
    for row in rows:row['tableData']=packet
    record={'synthesisEvidenceContractVersion':1,'question':'比较两篇','state':{'outputKind':'paper_comparison',
        'evidence':rows,'plan':[]}}
    sent=[]
    def update(_id,mutate,**kw):
        nonlocal record
        record=mutate(deepcopy(record));return deepcopy(record)
    def invoke(_id,node,prompt,options,**kw):
        sent.append(prompt);return {'finishReason':'length'}
    make_synthesize_node(invoke,update)({'run_id':'r'})
    assert len(sent)==1
    wire=json.JSONDecoder().raw_decode(sent[0].split('Evidence summaries:\n',1)[1])[0]
    assert len(wire)==3 and wire[0]['tableDataRef']==wire[1]['tableDataRef']!=wire[2]['tableDataRef']
    tables=json.JSONDecoder().raw_decode(sent[0].split('Shared table packets (tableDataRef resolves ONLY for its own source/evidence row):\n',1)[1])[0]
    assert len(tables)==2 and all(t['tableData']==packet for t in tables.values())


def test_new_beginner_rewrite_uses_dimensional_policy_without_claiming_scientific_approval():
    original={'claims':[{**claim('三维高斯使用共享模型。'),'obligationIds':['why']}],
              'sections':[{'title':'解释','claimIds':['c']}]}
    source=[evidence('e','Our 3D Gaussian model shares its representation across times.')]
    states=[];sent=[]
    def invoke(prompt,output):
        sent.append((prompt,output));return {'content':json.dumps({'claims':[{'claimId':'c',
            'text':'三维高斯共享表示，因此不同时间可以使用同一模型。','conditions':{}}]},ensure_ascii=False)}
    result=rewrite_for_beginner(original,source,'为新手解释为什么，300字以内',invoke,json.loads,
        contract_version=8,requirement_context=[{'obligationId':'why','question':'为什么共享模型'}],checkpoint=states.append)
    assert len(sent)==1 and sent[0][1]==3072 and result['claims'][0]['kind']=='inference'
    assert states[-1]['verificationPolicy']['quantity_spelling_version']==5
    assert states[-1]['classificationPrechecks'][0]['eligibleForSemanticCheck'] is True
    assert result['claims'][0].get('verification')!='semantic_passed'


@pytest.mark.parametrize('replacement',[None,True,0,'1',2])
def test_new_synthesis_contract_is_server_owned_and_cannot_retarget_saved_requests(tmp_path,replacement):
    repo=DeepResearchRepository(str(tmp_path/'r.sqlite3'));repo.initialize()
    facade=ResearchFacade(repo,lambda **_:None,llm_client=object())
    try:
        record,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'比较',
            'deferStart':True,'synthesisEvidenceContractVersion':replacement},start_async=False)
        assert record['synthesisEvidenceContractVersion']==1
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(record['runId'],lambda r:{**r,'synthesisEvidenceContractVersion':replacement})
    finally:facade.shutdown()
