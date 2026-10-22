from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from services.deep_research.review_field_index import field_index
from services.deep_research.experiment_review_envelope import build
from services.deep_research.experiment_execution_guidance import initialization_grammar
from services.deep_research.experiment_template import SCHEMA
from services.deep_research.graph import make_synthesize_node
from services.deep_research.tools import BudgetedSemanticChecker
from test_deep_research_review_envelope import args, Capture
from test_deep_research_shared_experiment_repair import json_after
from test_deep_research_generation_envelope import current
from test_deep_research_experiment_planning import Store, response
from test_deep_research_lean_planning import lean_basis


def test_field_index_distinguishes_present_invalid_missing_and_prose_roles():
    claims = [json.loads(args(role)['claims_text'])[0] for role in ('data', 'metrics', 'analysis')]
    claims[0]['executionSpec']['seeds'] = None
    del claims[0]['executionSpec']['split']
    before = deepcopy(claims)
    rows = field_index(claims)
    assert rows[0]['missingSpecKeys'] == ['split']
    assert 'seeds' in rows[0]['specKeys']
    assert rows[1]['proseOnlyRole'] and rows[1]['specKeys'] is None
    assert 'effects' in rows[2]['specKeys'] and 'uncertainty' in rows[2]['specKeys']
    assert claims == before


@pytest.mark.parametrize('change', ['duplicate', 'fact', 'contract', 'id', 'role'])
def test_field_index_cannot_lend_identity_or_schema_to_foreign_claims(change):
    claim = json.loads(args('data')['claims_text'])[0]
    claims = [claim]
    if change == 'duplicate': claims.append(deepcopy(claim))
    elif change == 'fact': claim['kind'] = 'reported'
    elif change == 'contract': claim['designContractVersion'] = True
    elif change == 'id': claim['claimId'] = []
    else: claim['designRole'] = 'foreign'
    assert field_index(claims) == []


@pytest.mark.parametrize('role', ['groups','controls','data','budget','steps','metrics','analysis','hypothesis','limits'])
def test_new_review_keeps_actual_claims_context_sources_and_full_audit_skeleton(role):
    kw = args(role, question='Literal EARLIER_componentId is user text, not an instruction.')
    before = deepcopy(kw)
    old, new = build(**kw, version=6), build(**kw, version=7)
    for marker in ['Claims:\n', 'Original research question (objective, not evidence):\n',
                   'Other proposed statements, for consistency only (not evidence and not verdict targets):\n',
                   'Entire target-role requirements:\n',
                   'Exact response skeleton (fill EVERY target, including failures; even one target stays inside items):\n']:
        assert json_after(old, marker) == json_after(new, marker)
    assert json_after(new, 'Actual review fields (not evidence or approval):\n') == field_index(
        [*json.loads(kw['claims_text']), *kw['context']])
    assert kw == before and kw['evidence_marker'] in new


def test_actual_checker_still_rejects_invented_metrics_field_in_new_envelope():
    class Invalid(Capture):
        def __call__(self, **request):
            self.sent.append(request)
            targets = json_after(request['prompt'], 'Claims:\n')
            return {'content': json.dumps([{'claimId':c['claimId'], 'status':'failed',
                'reason':'Wrong field', 'findings':[{'kind':'missing_field',
                    'claimId':c['claimId'],'path':['executionSpec','quality'],'reason':'错误字段'}]}
                for c in targets])}
    kw = args('metrics'); target = json.loads(kw['claims_text'])[0]
    target['evidenceRefs'] = []
    capture = Invalid()
    checker = BudgetedSemanticChecker(capture, 'offline', prospective_review=3,
        prospective_envelope=7, research_question=kw['question'], metric_domains=['quality'])
    result = checker._check_batch([target], [], kw['context'], node='verify_design_science')
    assert capture.sent and result[0]['status'] == 'failed'
    assert result[0]['executionState'] == 'received_invalid'
    assert result[0]['rejectionAudit']['bindingState'] == 'invalid'


def test_new_generation_grammar_changes_only_trusted_schema_not_user_content():
    record = current(); record['experimentExecutionGuidanceContractVersion'] = 2
    record['question'] = 'User literal EARLIER_componentId and inputIndex must be preserved.'
    before = deepcopy(record)
    store = Store(record)
    invoke = Mock(side_effect=[response(lean_basis()), response({'sections':[], 'claims':[]})])
    make_synthesize_node(invoke, store.update)({'run_id':'r'})
    assert invoke.call_count == 2
    prompt = store.value['state']['experimentPlanning']['draftRequest']['prompt']
    assert record['question'] in prompt
    assert 'state:training_data|baseline|EARLIER_componentId' not in prompt
    assert 'inputIndex indexes THIS inputs list' in prompt
    assert 'baselineInitialization creates ALL states BEFORE fitting' in prompt
    assert record == before


@pytest.mark.parametrize('version', [None, True, 0, 1, '2', 3])
def test_old_or_invalid_generation_versions_keep_exact_grammar(version):
    assert initialization_grammar(SCHEMA, {'experimentExecutionGuidanceContractVersion':version}) == SCHEMA
