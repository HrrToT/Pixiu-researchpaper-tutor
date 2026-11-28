from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.comparison_table_context import author_headers,for_record
from services.deep_research.table_bindings import validate_table_bindings
from services.deep_research.verification import make_evidence,verify_claims
from services.deep_research.reporting import render_report


def fixture(label='Ours'):
    quote=f'Table row 3: {label} | 134 | 734MB | 154 | 411MB'
    ev=make_evidence({'workId':'paper','versionId':'v1','contentHash':'hash','accessLevel':'fulltext'},
        quote,quote,location={'table':'t1'},obligation_ids=['o'])
    ev['tableData']={'groups':[['Dataset A',['FPS','Mem']],['Dataset B',['FPS','Mem']]],
                     'rows':[[3,label,['134','734MB','154','411MB']]]}
    claim={'claimId':'c','kind':'reported','text':'Dataset A 的 Method Alpha：FPS 134，Mem 734MB',
           'conditions':{},'obligationIds':['o'],'evidenceRefs':[ev['evidenceId']],
           'tableBindings':[{'evidenceId':ev['evidenceId'],'rowNumber':3,'groupIndex':0,'metric':'FPS','value':'134'},
                            {'evidenceId':ev['evidenceId'],'rowNumber':3,'groupIndex':0,'metric':'Mem','value':'734MB'}]}
    ctx={'version':3,'sources':{'P1':{'title':'Method Alpha','workId':'paper','versionId':'v1'}},
         'jointGoals':[],'layout':[{'source':'P1','obligationId':'o','question':'Storage and speed',
                                  'axisId':'axis','axisTitle':'存储与速度','claimIds':['c']}]}
    return claim,ev,ctx


def test_own_author_row_uses_exact_source_column_without_rewriting_body_or_evidence():
    claim,ev,ctx=fixture();before=deepcopy((claim,ev,ctx))
    assert validate_table_bindings(claim,[ev])=='table_condition_not_displayed'
    assert validate_table_bindings(claim,[ev],comparison_context=ctx) is None
    assert author_headers(claim,[ev],ctx)=={ev['evidenceId']:'Method Alpha'}
    assert (claim,ev,ctx)==before


@pytest.mark.parametrize('mutation',['work','version','missing_version','empty_title','ambiguous_cell',
    'wrong_goal','unknown_column','legacy','boolean_version','duplicate_evidence','unverified','foreign_ref','malformed_column'])
def test_unbound_or_ambiguous_display_context_cannot_authorize_author_row(mutation):
    claim,ev,ctx=fixture();evidence=[ev]
    if mutation=='work':ctx['sources']['P1']['workId']='other'
    elif mutation=='version':ctx['sources']['P1']['versionId']='v2'
    elif mutation=='missing_version':ctx['sources']['P1'].pop('versionId')
    elif mutation=='empty_title':ctx['sources']['P1']['title']=''
    elif mutation=='ambiguous_cell':ctx['layout'].append(deepcopy(ctx['layout'][0]))
    elif mutation=='wrong_goal':claim['obligationIds']=['another-goal']
    elif mutation=='unknown_column':ctx['layout'][0]['source']='P2'
    elif mutation=='malformed_column':ctx['layout'][0]['source']={}
    elif mutation=='legacy':ctx['version']=2
    elif mutation=='boolean_version':ctx['version']=True
    elif mutation=='duplicate_evidence':evidence.append(deepcopy(ev))
    elif mutation=='unverified':ev['verification']['literal']='failed'
    else:
        foreign={**deepcopy(ev),'evidenceId':'foreign','sourceWorkId':'other'}
        evidence.append(foreign);claim['evidenceRefs'].append('foreign')
    assert not author_headers(claim,evidence,ctx)
    assert validate_table_bindings(claim,evidence,comparison_context=ctx)=='table_condition_not_displayed'


@pytest.mark.parametrize('label',['Ours*','Ours (small)','Baseline A'])
def test_source_column_never_hides_baselines_or_variant_markers(label):
    claim,ev,ctx=fixture(label)
    assert validate_table_bindings(claim,[ev],comparison_context=ctx)=='table_condition_not_displayed'
    explicit=deepcopy(claim);explicit['text']+=f'（原表 {label}）'
    assert validate_table_bindings(explicit,[ev],comparison_context=ctx) is None


@pytest.mark.parametrize('mutation',['dataset','value','metric','row','group'])
def test_author_column_never_supplies_missing_conditions_or_corrects_cells(mutation):
    claim,ev,ctx=fixture()
    if mutation=='dataset':claim['text']=claim['text'].replace('Dataset A','Another dataset')
    elif mutation=='value':claim['tableBindings'][0]['value']='999'
    elif mutation=='metric':claim['tableBindings'][0]['metric']='PSNR'
    elif mutation=='row':claim['tableBindings'][0]['rowNumber']=99
    else:claim['tableBindings'][0]['groupIndex']=1
    assert validate_table_bindings(claim,[ev],comparison_context=ctx) is not None


@pytest.mark.parametrize('passed',[False,True,None])
def test_column_identity_still_requires_independent_semantic_verdict(passed):
    claim,ev,ctx=fixture()
    checker=None if passed is None else Mock(return_value=[{'claimId':'c','status':'passed' if passed else 'failed','reason':'Fixture scientific judgement.'}])
    result=verify_claims([claim],[ev],checker,table_references_version=3,comparison_context=ctx)
    assert bool(result['accepted']) is (passed is True)
    if checker:checker.assert_called_once()
    if passed is True:
        text=render_report({'claims':result['accepted'],'evidence':[ev],'comparisonCells':ctx,
                            'outputKind':'paper_comparison','presentationVersion':4})
        body,separator,sources=text.partition('<details>')
        assert separator and 'Method Alpha' in body and claim['text'] in body
        assert 'Ours' not in body
        assert ev['quote'] in sources


def test_facade_reads_live_server_layout_after_checker_creation(tmp_path):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    repo=DeepResearchRepository(tmp_path/'research.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **kwargs:None,llm_client=object(),comparison_cells_version=1)
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'比较两篇论文',
                             'outputKind':'paper_comparison'},start_async=False)
        checker=facade._get_verify_claims(run['runId'])
        claim,ev,ctx=fixture()
        draft={'layoutVersion':3,'sources':ctx['sources'],'layout':ctx['layout'],'jointGoals':[]}
        repo.update_run(run['runId'],lambda r:{**r,'state':{**r.get('state',{}),
            'outputKind':'paper_comparison','comparisonCellDraft':draft}})
        assert for_record(repo.require_run(run['runId']))==ctx
        semantic=Mock(return_value=[{'claimId':'c','status':'passed'}])
        assert checker([claim],[ev],semantic)['accepted']
        legacy={**repo.require_run(run['runId']),'runId':'legacy','idempotencyKey':'legacy-op',
                'comparisonPlanningContractVersion':1}
        saved,created=repo.create_run(legacy)
        assert created and saved['runId']=='legacy'
        assert not facade._get_verify_claims('legacy')([claim],[ev],semantic)['accepted']
    finally:
        facade.shutdown()


@pytest.mark.parametrize('mutation',['title','version','source','text'])
def test_author_column_display_is_bound_to_final_audited_answer(mutation):
    from services.deep_research.comparison_presentation import audit_digest,revalidate_audit
    claim,ev,ctx=fixture()
    audit={'comparisonPresentationDigest':audit_digest(ctx,[claim]),'gaps':[]}
    assert revalidate_audit(audit,ctx,[claim])==audit
    if mutation=='title':ctx['sources']['P1']['title']='Different method'
    elif mutation=='version':ctx['sources']['P1']['versionId']='v2'
    elif mutation=='source':ctx['sources']['P2']=deepcopy(ctx['sources']['P1']);ctx['layout'][0]['source']='P2'
    else:claim['text']+=' Unreviewed addition.'
    assert revalidate_audit(audit,ctx,[claim])['status']=='invalidated_comparison_presentation'
