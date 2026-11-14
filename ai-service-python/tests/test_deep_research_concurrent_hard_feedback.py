from copy import deepcopy
import json
from unittest.mock import Mock

from services.deep_research.repair import repair_rejected
from services.deep_research.verification import verify_claims
from test_deep_research_table_bindings import fixture


def test_numeric_rejection_also_reports_the_concurrent_exact_table_identity_failure():
    ev,c=fixture();c['text']=c['text'].replace('Ours*','CompressionMethod')+'，另有计算值0.08。'
    original=deepcopy([ev,c]);checker=Mock()
    old=verify_claims([c],[ev],checker,quantity_spelling_version=2,feedback_version=1)['rejected'][0]
    assert old['reason']=='numeric_mismatch' and 'additionalChecks' not in old
    new=verify_claims([c],[ev],checker,quantity_spelling_version=2,feedback_version=2)['rejected'][0]
    assert new['reason']=='numeric_mismatch' and new['missingReportedNumbers']==['8e-2']
    assert len(new['additionalChecks'])==1
    assert set(new['additionalChecks'][0])=={'reason','requiredTableDisplay','detail'}
    assert new['additionalChecks'][0]['reason']=='table_condition_not_displayed'
    assert new['additionalChecks'][0]['requiredTableDisplay']==[{'group':'Dataset A','method':'Ours*'}]
    checker.assert_not_called();assert [ev,c]==original


def test_one_revision_sees_both_errors_and_still_needs_the_unchanged_hard_and_semantic_checks():
    ev,valid=fixture();bad={**valid,'text':valid['text'].replace('Ours*','CompressionMethod')+'，计算值0.08。'}
    rejection=verify_claims([bad],[ev],quantity_spelling_version=2,feedback_version=2)
    def invoke(prompt):
        assert 'additionalChecks' in prompt and 'table_condition_not_displayed' in prompt
        assert '8e-2' in prompt and 'requiredTableDisplay' in prompt
        result=deepcopy(valid);result['evidenceRefs']=['E1']
        for b in result['tableBindings']:b['evidenceId']='E1'
        return {'content':json.dumps([result])}
    revised=repair_rejected({'claims':[bad]},rejection,[ev],'核查',invoke,json.loads)
    semantic=Mock(return_value=[{'claimId':'c','status':'passed'}])
    assert verify_claims(revised,[ev],semantic,quantity_spelling_version=2,feedback_version=2)['accepted']
    semantic.assert_called_once()
    assert not verify_claims(revised,[ev],quantity_spelling_version=2,feedback_version=2)['accepted']


def test_invalid_cell_details_are_not_silently_fixed_or_hidden_behind_a_numeric_error():
    ev,c=fixture();c['text']+='，计算值0.08。';c['tableBindings'][0]['value']='999'
    result=verify_claims([c],[ev],quantity_spelling_version=2,feedback_version=2)['rejected'][0]
    assert result['reason']=='numeric_mismatch'
    assert result['additionalChecks']==[{'reason':'table_cell_mismatch'}]
    assert c['tableBindings'][0]['value']=='999'
