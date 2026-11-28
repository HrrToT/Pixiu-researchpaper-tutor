from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from services.deep_research.audience_plain_explanations import notation_requested
from services.deep_research.audience_rewrite import _prepare,rewrite_for_beginner
from services.deep_research.contracts import DeepResearchError
from test_deep_research_audience_edit_budget import fixture,answer,options
from test_deep_research_audience_mapped_source import GOALS,targets

@pytest.mark.parametrize('q',['给出公式并解释。','请推导更新规则。','Explain β1.','Derive the equation.','先解释，再给公式。'])
def test_explicit_math_requests_keep_notation(q):assert notation_requested(q)

@pytest.mark.parametrize('q',['通俗解释方法。','不用公式，解释方法。','无需推导。','不要给出公式。','Explain without equations.','Do not give formulas.'])
def test_plain_or_negated_math_requests_do_not_restore_optional_formulas(q):assert not notation_requested(q)


def test_new_reader_retains_all_source_rows_metadata_and_budget():
    report,ev,q=fixture();before=deepcopy((report,ev))
    old,_=_prepare(report,ev,q,contract_version=9,requirement_context=GOALS,mapped_source_first=True)
    new,reason=_prepare(report,ev,q,contract_version=9,requirement_context=GOALS,mapped_source_first=True,plain_explanations=True)
    assert reason is None and new['prompt'].startswith(old['prompt'])
    assert targets(new)==targets(old) and new['outputTokens']==old['outputTokens']
    assert 'Reader wording contract2' in new['prompt'] and 'did not request formulas' in new['prompt']
    assert (report,ev)==before


def test_protected_edit_recursion_keeps_fixed_content_and_new_wording_contract():
    report,ev,q=fixture()
    request,reason=_prepare(report,ev,q,requirement_context=GOALS,mapped_source_first=True,plain_explanations=True,**options())
    assert reason is None and 'Reader wording contract2' in request['prompt']
    assert [t['claimId'] for t in targets(request)]==['edit']
    assert 'Fixed answer context' in request['prompt'] and report['claims'][1]['text'] in request['prompt']


def test_saved_response_reuse_rejects_protocol_change_without_resending():
    report,ev,q=fixture();states=[];invoke=Mock(return_value=answer())
    opts={**options(),'requirement_context':GOALS,'mapped_source_first':True,'plain_explanations':True}
    result=rewrite_for_beginner(report,ev,q,invoke,json.loads,checkpoint=states.append,**opts)
    assert states[-1]['audienceMappedSourceContractVersion']==2
    assert rewrite_for_beginner(report,ev,q,invoke,json.loads,saved_state=states[-1],**opts)==result
    assert invoke.call_count==1
    invoke.reset_mock()
    for mode in ('legacy','missing','boolean'):
        saved=deepcopy(states[-1]);kw=deepcopy(opts)
        if mode=='legacy':kw.pop('plain_explanations')
        elif mode=='missing':saved.pop('audienceMappedSourceContractVersion')
        else:saved['audienceMappedSourceContractVersion']=True
        with pytest.raises(DeepResearchError):rewrite_for_beginner(report,ev,q,invoke,json.loads,saved_state=saved,**kw)
    invoke.assert_not_called()
