import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from services.deep_research.answer_coverage import _bindings_supported, _known_claims_by_id
from services.deep_research.coverage_aspects import invalid_coverage_aspects
from services.deep_research.coverage_references import resolve_coverage_references
from services.deep_research.display_metadata import (
    answer_display_metadata, display_metadata_digest, revalidate_display_metadata)
from services.deep_research.final_coverage import audit_final_answer
from services.deep_research.reporting import render_report

QUESTION = '解释输入如何改变输出，并写明实际取得的是摘要还是全文。'
CLAIMS = [{'claimId': 'c', 'text': '输入增加时，模型会改变输出的预测方向。', 'conditions': {},
           'kind': 'reported', 'evidenceRefs': ['e'], 'sourceAccessSummary': '伪造的模型标签'}]
EVIDENCE = [{'evidenceId': 'e', 'quote': 'Increasing the input changes the predicted direction.',
             'accessLevel': 'fulltext', 'sourceKind': 'arxiv', 'sourceWorkId': 'paper'}]


def verdicts():
    binding = [{'claimId': 'c', 'field': 'text'}]
    aspects = [
        {'aspectId': 'science', 'requirement': '输入怎样改变输出', 'status': 'covered',
         'basis': {'kind': 'source', 'evidenceId': 'e', 'field': 'quote'}, 'bindings': binding},
        {'aspectId': 'access', 'requirement': '实际取得的材料范围', 'status': 'covered',
         'basis': {'kind': 'source_metadata', 'evidenceId': 'e', 'field': 'accessLevel',
                   'value': 'fulltext', 'requestExcerpt': '写明实际取得的是摘要还是全文'},
         'bindings': [{'claimId': 'c', 'field': 'sourceAccessSummary'}]}]
    return [{'obligationId': key, 'status': 'covered', 'bindings': deepcopy(binding),
             'aspects': deepcopy(aspects)} for key in ('o', 'answer_scope')]


def test_server_label_is_the_actual_rendered_answer_and_never_model_claim_metadata():
    metadata = answer_display_metadata(CLAIMS, EVIDENCE)
    assert metadata == {'sourceAccessSummary': '本回答引用：全文片段。'}
    assert render_report({'claims': CLAIMS, 'evidence': EVIDENCE}).startswith(metadata['sourceAccessSummary'])
    original = deepcopy(CLAIMS)
    call = Mock(return_value={'content': json.dumps(verdicts())})
    result = audit_final_answer('r', QUESTION, [{'obligations': [{'obligationId': 'o', 'question': QUESTION}]}],
                               CLAIMS, EVIDENCE, call, json.loads)
    assert result['status'] == 'checked' and result['gaps'] == []
    assert result['verdicts'][0]['aspects'][1]['bindings'][0]['excerpt'] == metadata['sourceAccessSummary']
    assert 'Server-rendered answer metadata:' in call.call_args.args[2]
    assert CLAIMS == original and CLAIMS[0]['conditions'] == {}


@pytest.mark.parametrize('change', ['wrong_level', 'uncited_evidence', 'unsupplied_evidence',
    'duplicate_claim', 'duplicate_evidence', 'no_display', 'scientific_request', 'scientific_basis',
    'literal_conflict', 'empty_conditions'])
def test_display_binding_cannot_forge_access_or_supply_scientific_content(change):
    rows, claims, evidence = deepcopy((verdicts()[:1], CLAIMS, EVIDENCE))
    metadata = answer_display_metadata(claims, evidence)
    aspect = rows[0]['aspects'][1]
    if change == 'wrong_level': aspect['basis']['value'] = 'abstract'
    elif change == 'uncited_evidence': claims[0]['evidenceRefs'] = ['other']
    elif change == 'unsupplied_evidence': evidence = []
    elif change == 'duplicate_claim': claims.append(deepcopy(claims[0]))
    elif change == 'duplicate_evidence': evidence.append(deepcopy(evidence[0]))
    elif change == 'no_display': metadata = {}
    elif change == 'scientific_request': aspect['basis']['requestExcerpt'] = '解释输入如何改变输出'
    elif change == 'scientific_basis': aspect['basis'] = {'kind': 'source', 'evidenceId': 'e', 'field': 'quote'}
    elif change == 'literal_conflict': aspect['bindings'][0]['excerpt'] = metadata['sourceAccessSummary']
    elif change == 'empty_conditions': aspect['bindings'][0]['field'] = 'conditions'
    resolved = resolve_coverage_references(rows, claims, evidence, display_metadata=metadata)
    assert invalid_coverage_aspects(resolved, claims, evidence, [QUESTION], display_metadata=metadata) == ['o']


@pytest.mark.parametrize('target', ['overall', 'criterion'])
def test_access_label_is_forbidden_in_overall_and_frozen_criterion_bindings(target):
    rows = verdicts()[:1]
    binding = {'claimId': 'c', 'field': 'sourceAccessSummary'}
    if target == 'overall': rows[0]['bindings'] = [binding]
    else: rows[0]['criteria'] = [{'criterionId': 'science', 'responseType': 'explanation',
                                'status': 'covered', 'bindings': [binding]}]
    resolved = resolve_coverage_references(rows, CLAIMS, EVIDENCE,
        display_metadata=answer_display_metadata(CLAIMS, EVIDENCE))
    found = resolved[0]['bindings'] if target == 'overall' else resolved[0]['criteria'][0]['bindings']
    assert found[0]['referenceError'] == 'answer_field_not_supplied'
    assert not _bindings_supported(found, _known_claims_by_id(CLAIMS))


def test_changed_individual_access_invalidates_resume_even_when_aggregate_label_is_unchanged():
    claims = [{**CLAIMS[0], 'evidenceRefs': ['e', 'b', 'c']}]
    evidence = [*EVIDENCE, {**EVIDENCE[0], 'evidenceId': 'b', 'accessLevel': 'abstract'},
                {**EVIDENCE[0], 'evidenceId': 'c', 'accessLevel': 'abstract'}]
    audit = {'status': 'checked', 'gaps': [], 'wholeQuestionId': 'scope',
             'displayMetadataDigest': display_metadata_digest(claims, evidence)}
    assert revalidate_display_metadata(audit, claims, list(reversed(evidence))) == audit
    changed = deepcopy(evidence)
    changed[1]['accessLevel'] = 'fulltext'
    assert answer_display_metadata(claims, changed) == answer_display_metadata(claims, evidence)
    result = revalidate_display_metadata(audit, claims, changed)
    assert result['status'] == 'invalidated_display_metadata' and result['gaps'][0]['obligationId'] == 'scope'
    assert revalidate_display_metadata({'status': 'checked'}, claims, changed) == {'status': 'checked'}


def test_only_cited_external_evidence_causes_a_visible_label():
    assert answer_display_metadata(CLAIMS, [{**EVIDENCE[0], 'sourceKind': 'local'}]) == {}
    assert answer_display_metadata([{**CLAIMS[0], 'evidenceRefs': []}], EVIDENCE) == {}
    missing = [{**CLAIMS[0], 'evidenceRefs': ['e', 'not-acquired']}]
    assert '访问范围未标明' in answer_display_metadata(missing, EVIDENCE)['sourceAccessSummary']
