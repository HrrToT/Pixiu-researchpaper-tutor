from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.final_coverage import remaining_retrieval_gaps
from services.deep_research.graph import make_publish_node
from test_deep_research_coverage_revision_flow import EVIDENCE,FULL,audit_rows


def fixture():
    work='arxiv:2406.01467';version=work+'v1'
    gap={'obligationId':'o','sourceWorkId':version,'question':'必要条件？'}
    evidence=deepcopy(EVIDENCE);evidence[0].update(sourceWorkId=work,sourceVersionId=version)
    claims=[{'claimId':'c','text':FULL,'kind':'reported','verification':'semantic_passed','evidenceRefs':['e']}]
    audit={'status':'checked','gaps':[],'verdicts':audit_rows(FULL,'covered')}
    return gap,evidence,claims,audit


def test_exact_version_can_close_only_after_literal_fact_and_final_answer_verification():
    gap,evidence,claims,audit=fixture();before=deepcopy((gap,evidence,claims,audit))
    assert remaining_retrieval_gaps([gap],audit,claims,evidence)==[gap]
    assert remaining_retrieval_gaps([gap],audit,claims,evidence,versioned_sources=True)==[]
    assert (gap,evidence,claims,audit)==before
    unversioned={**gap,'sourceWorkId':'arxiv:2406.01467'}
    assert remaining_retrieval_gaps([unversioned],audit,claims,evidence,versioned_sources=True)==[]


@pytest.mark.parametrize('change',['different_version','different_work','inconsistent_identity','missing_version',
    'unverified_fact','proposal','unverified_quote','unbound_quote','partial_answer','unchecked_answer'])
def test_wrong_revision_or_missing_verification_never_closes_the_gap(change):
    gap,evidence,claims,audit=fixture()
    if change=='different_version':evidence[0]['sourceVersionId']='arxiv:2406.01467v2'
    elif change=='different_work':evidence[0].update(sourceWorkId='arxiv:2308.04079',sourceVersionId='arxiv:2308.04079v1')
    elif change=='inconsistent_identity':evidence[0]['sourceWorkId']='arxiv:2308.04079'
    elif change=='missing_version':evidence[0].pop('sourceVersionId')
    elif change=='unverified_fact':claims[0]['verification']='unchecked'
    elif change=='proposal':claims[0]['kind']='proposal'
    elif change=='unverified_quote':evidence[0]['verification']['literal']='unchecked'
    elif change=='unbound_quote':claims[0]['evidenceRefs']=[]
    elif change=='partial_answer':audit['verdicts']=audit_rows(FULL,'partial')
    else:audit['status']='invalid_response'
    assert remaining_retrieval_gaps([gap],audit,claims,evidence,versioned_sources=True)==[gap]


@pytest.mark.parametrize('contract,expected',[(None,'partial'),(True,'partial'),(2,'partial'),(1,'complete')])
def test_publication_routes_new_contract_without_rewriting_the_historical_gap(contract,expected):
    gap,evidence,claims,audit=fixture()
    record={'sourceGapClosureContractVersion':contract,'state':{'outputKind':'claim_verification',
        'plan':[{'obligations':[{'obligationId':'o','question':'必要条件？'}]}],
        'evidence':evidence,'gaps':[gap],'verifiedReport':{'verifiedClaims':claims,'rejectedClaims':[],
                                                      'answerCoverage':audit}}}
    def update(run,change,**kwargs):
        nonlocal record
        record=change(record);return record
    publish=Mock(return_value=({'publicationId':'pub'},True))
    result=make_publish_node(publish,update)({'run_id':'r','report_version_id':'v'})
    assert result['outcome']==expected
    assert publish.call_args.kwargs['payload']['gaps']==([] if expected=='complete' else [gap])
    assert record['state']['gaps']==[gap]
