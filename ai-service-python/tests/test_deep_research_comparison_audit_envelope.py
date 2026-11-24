from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.comparison_audit_envelope import CORRECTION_POLICY, decode, enabled, POLICY
from services.deep_research.coverage_binding_correction import GUIDANCE
from services.deep_research.structured_output import normalize, messages_for_record


def value():
    return {'items':[{'obligationId':'o','checks':[]}], 'auditType':'answer_coherence',
            'coherent':True,'issues':[]}


@pytest.mark.parametrize('mutation',['extra','missing','double','type','items','row','audit','duplicate','nan','length'])
def test_only_complete_unambiguous_object_is_decoded(mutation):
    obj=value();finish='stop'
    if mutation=='extra':obj['other']=1
    elif mutation=='missing':obj.pop('issues')
    elif mutation=='double':obj['items'].append({'auditType':'answer_coherence','coherent':True,'issues':[]})
    elif mutation=='type':obj['coherent']=1
    elif mutation=='items':obj['items']={}
    elif mutation=='row':obj['items']=[None]
    elif mutation=='audit':obj['auditType']='different'
    elif mutation=='length':finish='length'
    raw=json.dumps(obj)
    if mutation=='duplicate':raw=raw[:-1]+',"coherent":false}'
    elif mutation=='nan':raw=raw.replace('true','NaN')
    out=normalize('verify_answer_coverage',{'content':raw,'finishReason':finish},comparison_audit_envelope=True)
    assert out['content']=='null' and out['rawContent']==raw


def test_transport_does_not_modify_rows_or_upgrade_negative_coherence():
    obj=value();obj.update(coherent=False,issues=[{'kind':'contradiction','bindings':[],'reason':'Unresolved conflict.'}])
    before=deepcopy(obj);rows=decode(obj)
    assert rows[:-1]==obj['items'] and rows[-1]=={k:obj[k] for k in ('auditType','coherent','issues')}
    assert obj==before
    raw=json.dumps(obj)
    assert json.loads(normalize('verify_answer_coverage',{'content':raw},comparison_audit_envelope=True)['content'])==rows
    assert normalize('verify_answer_coverage',{'content':raw})['content']=='null'
    with pytest.raises(ValueError):normalize('verify',{'content':raw},comparison_audit_envelope=True)


def test_new_server_run_freezes_envelope_and_actual_invoker_decodes_it(tmp_path,monkeypatch):
    from services.deep_research.repository import DeepResearchRepository
    from services.deep_research.facade import ResearchFacade
    from services.deep_research.tools import TrackedLLMInvoker
    from llm.client import DeepSeekLLM
    repo=DeepResearchRepository(tmp_path/'r.sqlite3');repo.initialize()
    facade=ResearchFacade(repo,lambda **kwargs:None,llm_client=object(),comparison_cells_version=1)
    try:
        run,_=facade.create({'workspaceTaskId':'t','operationKey':'op','question':'比较论文',
            'outputKind':'paper_comparison'},start_async=False)
        rid=run['runId']
        run=repo.update_run(rid,lambda r:{**r,'state':{**r.get('state',{}),'outputKind':'paper_comparison'}})
        assert enabled(run) and run['comparisonAuditEnvelopeContractVersion']==8
        assert messages_for_record(run,'verify_answer_coverage','prompt')[0]['content']==POLICY
        for version in [None,0,True,9999]:
            old={**run,'comparisonAuditEnvelopeContractVersion':version}
            assert not enabled(old)
            assert messages_for_record(old,'verify_answer_coverage','prompt')[0]['content']!=POLICY
        assert not enabled(run,'verify')
        with pytest.raises(ValueError,match='Immutable'):
            repo.update_run(rid,lambda r:{**r,'comparisonAuditEnvelopeContractVersion':0})
        repo.begin_execution(rid)
        raw=json.dumps(value());http=Mock(status_code=200)
        http.json.return_value={'choices':[{'message':{'content':raw},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':5,'completion_tokens':2,'total_tokens':7}}
        sends=[]
        def post(url,**kwargs):sends.append(kwargs['json']);return http
        monkeypatch.setattr('llm.client.requests.post',post)
        client=DeepSeekLLM(api_key='fixture',base_url='https://fixture.invalid',timeout_seconds=2)
        invoke=TrackedLLMInvoker(client,repo.reserve_call,repo.complete_call,run_record_fn=repo.require_run)
        result=invoke(rid,'verify_answer_coverage','prompt',{'max_tokens':200})
        assert sends[0]['messages'][0]['content']==POLICY and len(sends)==1
        assert result['rawContent']==raw and json.loads(result['content'])==decode(value())
        assert result['structuredOutput']['receivedShape']=='comparison_audit_v1'
        cached=invoke(rid,'verify_answer_coverage','prompt',{'max_tokens':200})
        assert cached==result and len(sends)==1

        correction_prompt = GUIDANCE + '\nFrozen review inputs:\n{}'
        old_run = {**run, 'comparisonAuditEnvelopeContractVersion': 1}
        assert messages_for_record(old_run, 'verify_answer_coverage', correction_prompt)[0]['content'] == POLICY
        rows = [{'obligationId': 'o', 'checkId': 'criterion:C2', 'status': 'partial',
                 'processLinks': [], 'reason': 'Only one of the two papers is described.'}]
        for shape, payload in [('items', {'items': rows}), ('array_compat', rows)]:
            raw = json.dumps(payload)
            http.json.return_value['choices'][0]['message']['content'] = raw
            prompt = correction_prompt + '\n' + shape
            corrected = invoke(rid, 'verify_answer_coverage', prompt, {'max_tokens': 200})
            assert sends[-1]['messages'][0]['content'] == CORRECTION_POLICY
            assert 'Return ONLY {"items":[...]}' in sends[-1]['messages'][1]['content']
            assert corrected['rawContent'] == raw and json.loads(corrected['content']) == rows
            assert corrected['structuredOutput']['receivedShape'] == shape
            assert invoke(rid, 'verify_answer_coverage', prompt, {'max_tokens': 200}) == corrected
        assert len(sends) == 3
    finally:facade.shutdown()
