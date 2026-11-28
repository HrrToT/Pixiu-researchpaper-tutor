import copy
import unittest

from services.deep_research.coverage_repair import (
    merge_verified_revisions,
    prepare_coverage_repair,
)


def _claim(cid, obligations, text):
    return {"claimId": cid, "obligationIds": list(obligations), "text": text}


def _camera_claims():
    return [
        _claim("c1", ["o1"], "Checkerboard corner detection localizes camera intrinsics."),
        _claim("c2", ["o2"], "Bundle adjustment refines camera extrinsics."),
        _claim("c3", ["o1", "o3"], "Radial distortion model lowers reprojection error."),
    ]


def test_scoped_repair_preserves_a_covered_claim_used_as_review_context():
    calculation = _claim('calculation', ['compute'], 'Predict and sort the two coordinates.')
    limit = _claim('limit', ['scope'], 'Uniform marginals do not establish a uniform joint distribution.')
    claims = [calculation, limit]
    bindings = [{'claimId': claim['claimId']} for claim in claims]
    audit = {'status': 'checked', 'requestCoverageContractVersion': 5,
             'gaps': [{'obligationId': 'compute', 'question': 'How is the loss computed?'},
                      {'obligationId': 'answer_scope', 'question': 'Explain loss and scope.', 'wholeQuestion': True}],
             'verdicts': [{'obligationId': oid, 'bindings': bindings} for oid in ('compute', 'answer_scope')]}
    verified = {'accepted': claims, 'rejected': []}
    old = prepare_coverage_repair({'claims': claims}, verified, audit, prioritize_specific=True)
    assert old['accepted'] == []
    scoped = prepare_coverage_repair({'claims': claims}, verified, audit,
                                    prioritize_specific=True, prefer_bound_claims=True)
    assert scoped['accepted'] == [limit]
    assert [row['claimId'] for row in scoped['rejected']] == ['calculation']


def test_beginner_gap_repairs_only_the_measured_lead():
    claims = [_claim('lead', ['example'], 'Matched measurements.'),
              _claim('boundary', ['scope'], 'No direct cross-paper ranking.'),
              _claim('mechanism', ['mechanism'], 'Pruning removes selected elements.')]
    excerpt = '向初学者比较原始表示与压缩后部署的取舍'
    gap = {'obligationId': 'answer_scope', 'wholeQuestion': True,
           'question': excerpt + '。再列出比较表。', 'missingRequestExcerpt': excerpt}
    audit = {'status': 'checked', 'requestCoverageContractVersion': 5, 'gaps': [gap],
             'verdicts': [{'obligationId': 'answer_scope',
                           'bindings': [{'claimId': c['claimId']} for c in claims]}]}
    verification = {'accepted': claims, 'rejected': []}
    scoped = prepare_coverage_repair({'claims': claims}, verification, audit,
                                    prioritize_specific=True, bound_comparison_targets=True,
                                    beginner_lead_claim_id='lead')
    assert [row['claimId'] for row in scoped['accepted']] == ['boundary', 'mechanism']
    assert scoped['rejected'] == [{'claimId': 'lead', 'reason': 'answer_incomplete',
                                   'missingQuestions': [excerpt], 'beginnerLeadRepair': True}]
    for value in (None, '说明为什么不能直接比较FPS'):
        other = {**audit, 'gaps': [{**gap, 'missingRequestExcerpt': value}]}
        unscoped = prepare_coverage_repair({'claims': claims}, verification, other,
                                          prioritize_specific=True, bound_comparison_targets=True,
                                          beginner_lead_claim_id='lead')
        assert unscoped['accepted'] == []


def test_beginner_term_gap_repairs_only_mechanism_cells_that_use_the_terms():
    claims = [_claim('lead', ['example'], '向量量化后的测试结果。'),
              _claim('left', ['mechanism'], '球谐系数描述颜色。'),
              _claim('right', ['mechanism'], '球谐系数、蒸馏和向量量化。'),
              _claim('cost', ['cost'], '向量量化处理成本。')]
    report = {'claims': claims, 'comparisonCells': {'layout': [
        {'axisTitle': '表示与压缩机制', 'claimIds': ['left']},
        {'axisTitle': '表示与压缩机制', 'claimIds': ['right']},
        {'axisTitle': '额外处理成本', 'claimIds': ['cost']},
    ]}}
    excerpt = '向初学者比较原始表示与压缩后部署的取舍'
    gap = {'obligationId': 'answer_scope', 'wholeQuestion': True, 'question': excerpt,
           'missingRequestExcerpt': excerpt}
    audit = {'status': 'checked', 'requestCoverageContractVersion': 5, 'gaps': [gap], 'diagnosticErrors': [],
             'wholeQuestionDiagnostic': {'requestExcerpt': excerpt,
                 'missingAnswerElement': '球谐系数、蒸馏和向量量化等核心术语缺少面向初学者的解释。'}}
    verification = {'accepted': claims, 'rejected': []}
    kwargs = dict(prioritize_specific=True, bound_comparison_targets=True, beginner_lead_claim_id='lead')
    routed = prepare_coverage_repair(report, verification, audit, beginner_term_repair=True, **kwargs)
    assert [row['claimId'] for row in routed['accepted']] == ['lead', 'cost']
    left, right = routed['rejected']
    assert left['claimId'] == 'left' and '球谐系数' in left['missingQuestions'][1]
    assert '向量量化' not in left['missingQuestions'][1]
    assert right['claimId'] == 'right' and '球谐系数、蒸馏、向量量化' in right['missingQuestions'][1]
    assert not any('beginnerLeadRepair' in row for row in routed['rejected'])
    assert prepare_coverage_repair(report, verification, audit, beginner_term_repair=True,
                                   **{**kwargs, 'beginner_lead_claim_id': None}) == routed
    assert prepare_coverage_repair(report, verification, audit, **kwargs)['rejected'][0]['claimId'] == 'lead'
    invalid = {**audit, 'wholeQuestionDiagnostic': {**audit['wholeQuestionDiagnostic'], 'requestExcerpt': '其他问题'}}
    assert prepare_coverage_repair(report, verification, invalid, beginner_term_repair=True, **kwargs)['rejected'][0]['claimId'] == 'lead'


def test_merge_initial_conflicting_identity_stays_rejected():
    claim = _claim('c', ['o'], 'ambiguous')
    initial = {'accepted': [claim], 'rejected': [{'claimId': 'c', 'reason': 'failed'}]}
    for checked in ({}, {'accepted': [claim]}):
        result = merge_verified_revisions(initial, checked)
        assert result['accepted'] == []
        assert result['rejected'] == initial['rejected']


def test_merge_conflicting_revision_cannot_promote_failed_claim():
    claim = _claim('c', ['o'], 'conflicting revision')
    initial = {'accepted': [], 'rejected': [{'claimId': 'c', 'reason': 'failed'}]}
    result = merge_verified_revisions(initial, {'accepted': [claim],
        'rejected': [{'claimId': 'c', 'reason': 'also failed'}]})
    assert result == initial


def test_merge_conflicting_revision_preserves_unambiguous_previous_acceptance():
    claim = _claim('c', ['o'], 'previously checked')
    initial = {'accepted': [claim], 'rejected': []}
    result = merge_verified_revisions(initial, {'accepted': [{**claim, 'text': 'ambiguous'}],
        'rejected': [{'claimId': 'c', 'reason': 'failed'}]})
    assert result == initial


def test_failed_revision_preserves_both_draft_and_current_failure_without_mutation():
    initial = {'accepted': [], 'rejected': [{'claimId': 'c6', 'reason': 'semantic_unresolved',
        'detail': 'Original subset is unconfirmed', 'missingQuestions': ['Select concrete data']}]}
    checked = {'accepted': [], 'rejected': [{'claimId': 'c6', 'reason': 'semantic_unresolved',
        'detail': 'DA_MISSING'}]}
    before = copy.deepcopy((initial, checked))
    result = merge_verified_revisions(initial, checked)
    assert result['rejected'][0]['detail'] == 'Original subset is unconfirmed'
    assert result['rejected'][0]['revisionRejection'] == checked['rejected'][0]
    assert (initial, checked) == before
    result['rejected'][0]['revisionRejection']['detail'] = 'edited'
    assert checked['rejected'][0]['detail'] == 'DA_MISSING'


def test_ambiguous_revision_failures_do_not_overwrite_history():
    initial = {'accepted': [], 'rejected': [{'claimId': 'c', 'reason': 'original'}]}
    checked = {'accepted': [], 'rejected': [{'claimId': 'c', 'reason': 'one'},
        {'claimId': 'c', 'reason': 'two'}, {'claimId': 'unknown', 'reason': 'unknown'}]}
    assert merge_verified_revisions(initial, checked) == initial


class PrepareCoverageRepairTests(unittest.TestCase):
    def test_empty_completion_slot_does_not_steal_gap_from_existing_method_claim(self):
        method = {**_claim('method', ['mechanism'], 'Incomplete intervention definition.'),
                  'kind': 'proposal', 'designRole': 'groups'}
        slot = {'claimId': 'data_slot', 'text': '', 'kind': 'proposal', 'designRole': 'data',
                'obligationIds': ['mechanism', 'data_availability']}
        verification = {'accepted': [method], 'rejected': [{'claimId': 'data_slot',
                        'reason': 'missing_design_deliverable'}]}
        audit = {'gaps': [{'obligationId': 'mechanism', 'question': 'Define the intervention score.'}],
                 'verdicts': [{'obligationId': 'mechanism', 'bindings': [{'claimId': 'method'}]}]}
        result = prepare_coverage_repair({'claims': [method, slot]}, verification, audit)
        assert result['accepted'] == []
        rejected = {row['claimId']: row for row in result['rejected']}
        assert rejected['method']['missingQuestions'] == ['Define the intervention score.']
        assert 'missingQuestions' not in rejected['data_slot']

    def test_existing_failed_target_prevents_rewriting_all_shared_obligation_claims(self):
        claims = [_claim('good', ['shared'], 'Known supported result'),
                  _claim('bad', ['shared'], 'Incomplete proposed method')]
        audit = {'gaps': [{'obligationId': 'shared', 'question': 'Complete the method'}],
                 'verdicts': [{'obligationId': 'shared', 'status': 'partial',
                               'bindings': [{'claimId': 'good', 'excerpt': 'Known supported result'}]}]}
        before = copy.deepcopy(audit)
        result = prepare_coverage_repair({'claims': claims}, {'accepted': [claims[0]],
            'rejected': [{'claimId': 'bad', 'reason': 'semantic_unresolved'}]}, audit)
        self.assertEqual([c['claimId'] for c in result['accepted']], ['good'])
        self.assertEqual([c['claimId'] for c in result['rejected']], ['bad'])
        self.assertEqual(result['rejected'][0]['missingQuestions'], ['Complete the method'])
        self.assertEqual(audit, before)  # Scheduling does not erase or resolve the gap.

    def test_targets_accepted_claim_via_verdict_bindings(self):
        claims = _camera_claims()
        report = {"claims": claims}
        verification = {"accepted": [claims[0], claims[1]], "rejected": []}
        audit = {
            "gaps": [
                {"obligationId": "o2", "question": "How is scale ambiguity resolved?", "wholeQuestion": False}
            ],
            "verdicts": [
                {
                    "obligationId": "o2",
                    "status": "partial",
                    "bindings": [{"claimId": "c2", "excerpt": "extrinsics"}],
                }
            ],
        }

        result = prepare_coverage_repair(report, verification, audit)

        self.assertEqual([c["claimId"] for c in result["accepted"]], ["c1"])
        self.assertEqual(len(result["rejected"]), 1)
        row = result["rejected"][0]
        self.assertEqual(row["claimId"], "c2")
        self.assertEqual(row["reason"], "answer_incomplete")
        self.assertEqual(row["missingQuestions"], ["How is scale ambiguity resolved?"])

    def test_targets_via_obligation_ids_without_bindings(self):
        claims = _camera_claims()
        report = {"claims": claims}
        verification = {"accepted": [claims[0], claims[2]], "rejected": []}
        audit = {
            "gaps": [
                {"obligationId": "o3", "question": "How is distortion validated?", "wholeQuestion": False}
            ],
            "verdicts": [],
        }

        result = prepare_coverage_repair(report, verification, audit)

        self.assertEqual([c["claimId"] for c in result["accepted"]], ["c1"])
        self.assertEqual([r["claimId"] for r in result["rejected"]], ["c3"])
        self.assertEqual(result["rejected"][0]["missingQuestions"], ["How is distortion validated?"])

    def test_unmapped_specific_gap_targets_all_accepted_report_claims(self):
        claims = _camera_claims()
        report = {"claims": claims}
        verification = {"accepted": [claims[0], claims[1]], "rejected": []}
        audit = {
            "gaps": [
                {"obligationId": "o9", "question": "How is temporal sync handled?", "wholeQuestion": False}
            ],
            "verdicts": [],
        }

        result = prepare_coverage_repair(report, verification, audit)

        self.assertEqual(result["accepted"], [])
        self.assertEqual(sorted(r["claimId"] for r in result["rejected"]), ["c1", "c2"])
        for row in result["rejected"]:
            self.assertEqual(row["reason"], "answer_incomplete")
            self.assertEqual(row["missingQuestions"], ["How is temporal sync handled?"])

    def test_whole_question_gap_ignored_when_specific_gap_present(self):
        claims = _camera_claims()
        report = {"claims": claims}
        verification = {"accepted": [claims[0], claims[1], claims[2]], "rejected": []}
        audit = {
            "gaps": [
                {"obligationId": "o2", "question": "How is scale ambiguity resolved?", "wholeQuestion": False},
                {"obligationId": "oX", "question": "Is everything covered?", "wholeQuestion": True},
            ],
            "verdicts": [
                {
                    "obligationId": "o2",
                    "status": "partial",
                    "bindings": [{"claimId": "c2", "excerpt": "extrinsics"}],
                }
            ],
        }

        result = prepare_coverage_repair(report, verification, audit)

        self.assertEqual([c["claimId"] for c in result["accepted"]], ["c1", "c3"])
        self.assertEqual([r["claimId"] for r in result["rejected"]], ["c2"])

    def test_original_rejection_preserved_alongside_coverage_targets(self):
        claims = _camera_claims()
        report = {"claims": claims}
        verification = {
            "accepted": [claims[0], claims[1]],
            "rejected": [{"claimId": "c0", "reason": "fabricated_source"}],
        }
        audit = {
            "gaps": [
                {"obligationId": "o1", "question": "How are intrinsics validated?", "wholeQuestion": False}
            ],
            "verdicts": [
                {
                    "obligationId": "o1",
                    "status": "partial",
                    "bindings": [{"claimId": "c1", "excerpt": "intrinsics"}],
                }
            ],
        }

        result = prepare_coverage_repair(report, verification, audit)

        ids = [r["claimId"] for r in result["rejected"]]
        self.assertIn("c0", ids)
        self.assertIn("c1", ids)
        original = next(r for r in result["rejected"] if r["claimId"] == "c0")
        self.assertEqual(original["reason"], "fabricated_source")
        coverage = next(r for r in result["rejected"] if r["claimId"] == "c1")
        self.assertEqual(coverage["reason"], "answer_incomplete")

    def test_no_gaps_returns_equivalent_copy(self):
        claims = _camera_claims()
        report = {"claims": claims}
        verification = {"accepted": [claims[0]], "rejected": [{"claimId": "cx", "reason": "off_topic"}]}
        audit = {"gaps": [], "verdicts": []}

        result = prepare_coverage_repair(report, verification, audit)

        self.assertEqual(result["accepted"], verification["accepted"])
        self.assertEqual(result["rejected"], verification["rejected"])
        self.assertIsNot(result["accepted"], verification["accepted"])
        self.assertIsNot(result["rejected"], verification["rejected"])

    def test_no_accepted_claims_invents_no_targets(self):
        claims = _camera_claims()
        report = {"claims": claims}
        verification = {"accepted": [], "rejected": [{"claimId": "c1", "reason": "low_confidence"}]}
        audit = {
            "gaps": [
                {"obligationId": "o1", "question": "How are intrinsics validated?", "wholeQuestion": False}
            ],
            "verdicts": [],
        }

        result = prepare_coverage_repair(report, verification, audit)

        self.assertEqual(result["accepted"], [])
        self.assertEqual([r["claimId"] for r in result["rejected"]], ["c1"])
        self.assertEqual(result["rejected"][0]["reason"], "low_confidence")

    def test_unknown_binding_ids_are_not_invented(self):
        claims = _camera_claims()
        report = {"claims": claims}
        verification = {"accepted": [claims[0]], "rejected": []}
        audit = {
            "gaps": [
                {"obligationId": "o2", "question": "How is scale ambiguity resolved?", "wholeQuestion": False}
            ],
            "verdicts": [
                {
                    "obligationId": "o2",
                    "status": "partial",
                    "bindings": [{"claimId": "c999", "excerpt": "ghost"}],
                }
            ],
        }

        result = prepare_coverage_repair(report, verification, audit)

        self.assertNotIn("c999", [r["claimId"] for r in result["rejected"]])
        self.assertNotIn("c999", [c["claimId"] for c in result["accepted"]])

    def test_inputs_are_not_mutated(self):
        claims = _camera_claims()
        report = {"claims": claims}
        verification = {
            "accepted": [claims[0], claims[1]],
            "rejected": [{"claimId": "c0", "reason": "fabricated_source"}],
        }
        audit = {
            "gaps": [
                {"obligationId": "o2", "question": "How is scale ambiguity resolved?", "wholeQuestion": False}
            ],
            "verdicts": [
                {
                    "obligationId": "o2",
                    "status": "partial",
                    "bindings": [{"claimId": "c2", "excerpt": "extrinsics"}],
                }
            ],
        }

        report_snap = copy.deepcopy(report)
        verification_snap = copy.deepcopy(verification)
        audit_snap = copy.deepcopy(audit)

        prepare_coverage_repair(report, verification, audit)

        self.assertEqual(report, report_snap)
        self.assertEqual(verification, verification_snap)
        self.assertEqual(audit, audit_snap)


class MergeVerifiedRevisionsTests(unittest.TestCase):
    def test_successful_replacement_appears_once(self):
        initial = {"accepted": [_claim("c1", ["o1"], "draft intrinsics")], "rejected": []}
        checked = {"accepted": [_claim("c1", ["o1"], "corrected intrinsics")], "rejected": []}

        result = merge_verified_revisions(initial, checked)

        self.assertEqual(len(result["accepted"]), 1)
        self.assertEqual(result["accepted"][0]["text"], "corrected intrinsics")
        self.assertEqual(result["rejected"], [])

    def test_failed_repair_retains_original_accepted(self):
        initial = {"accepted": [_claim("c1", ["o1"], "draft intrinsics")], "rejected": []}
        checked = {"accepted": [], "rejected": [{"claimId": "c1", "reason": "still_incomplete"}]}

        result = merge_verified_revisions(initial, checked)

        self.assertEqual(len(result["accepted"]), 1)
        self.assertEqual(result["accepted"][0]["text"], "draft intrinsics")

    def test_repaired_original_rejection_promoted(self):
        initial = {
            "accepted": [_claim("c1", ["o1"], "intrinsics")],
            "rejected": [
                {"claimId": "c2", "reason": "answer_incomplete", "missingQuestions": ["How is scale ambiguity resolved?"]}
            ],
        }
        checked = {"accepted": [_claim("c2", ["o2"], "extrinsics repaired")], "rejected": []}

        result = merge_verified_revisions(initial, checked)

        self.assertEqual([c["claimId"] for c in result["accepted"]], ["c1", "c2"])
        self.assertEqual(result["rejected"], [])

    def test_unknown_checked_accepted_ignored(self):
        initial = {"accepted": [_claim("c1", ["o1"], "intrinsics")], "rejected": []}
        checked = {"accepted": [_claim("c999", ["o9"], "ghost claim")], "rejected": []}

        result = merge_verified_revisions(initial, checked)

        self.assertEqual([c["claimId"] for c in result["accepted"]], ["c1"])

    def test_duplicate_checked_accepted_ignored(self):
        initial = {"accepted": [_claim("c1", ["o1"], "draft intrinsics")], "rejected": []}
        checked = {
            "accepted": [_claim("c1", ["o1"], "rev a"), _claim("c1", ["o1"], "rev b")],
            "rejected": [],
        }

        result = merge_verified_revisions(initial, checked)

        self.assertEqual(len(result["accepted"]), 1)
        self.assertEqual(result["accepted"][0]["text"], "draft intrinsics")

    def test_initial_rejection_retained_on_failed_repair(self):
        initial = {
            "accepted": [],
            "rejected": [{"claimId": "c2", "reason": "answer_incomplete", "missingQuestions": ["q"]}],
        }
        checked = {"accepted": [], "rejected": [{"claimId": "c2", "reason": "still_incomplete"}]}

        result = merge_verified_revisions(initial, checked)

        self.assertEqual(result["accepted"], [])
        self.assertEqual(len(result["rejected"]), 1)
        self.assertEqual(result["rejected"][0]["reason"], "answer_incomplete")

    def test_merge_does_not_mutate_inputs(self):
        initial = {
            "accepted": [_claim("c1", ["o1"], "intrinsics")],
            "rejected": [{"claimId": "c2", "reason": "answer_incomplete", "missingQuestions": ["q"]}],
        }
        checked = {"accepted": [_claim("c2", ["o2"], "extrinsics repaired")], "rejected": []}

        initial_snap = copy.deepcopy(initial)
        checked_snap = copy.deepcopy(checked)

        merge_verified_revisions(initial, checked)

        self.assertEqual(initial, initial_snap)
        self.assertEqual(checked, checked_snap)


if __name__ == "__main__":
    unittest.main()


def test_missing_joint_comparison_does_not_withhold_unrelated_verified_local_fact():
    from services.deep_research.coverage_repair import prepare_coverage_repair
    claim={'claimId':'metrics','kind':'reported','text':'有来源的单论文结果。','obligationIds':['local']}
    report={'claims':[claim]};verification={'accepted':[claim],'rejected':[]}
    audit={'status':'checked','requestCoverageContractVersion':5,'diagnosticErrors':[],
           'gaps':[{'obligationId':'joint','question':'这些条件能否比较？'}],'verdicts':[]}
    snapshot=copy.deepcopy((report,verification,audit))
    legacy=prepare_coverage_repair(report,verification,audit)
    scoped=prepare_coverage_repair(report,verification,audit,bound_comparison_targets=True)
    assert legacy['rejected'] and not legacy['accepted']
    assert scoped['accepted']==[claim] and not scoped['rejected']
    assert (report,verification,audit)==snapshot  # The missing answer stays missing in its audit.
    audit['gaps'][0]['obligationId']='local'
    assert prepare_coverage_repair(report,verification,audit,bound_comparison_targets=True)['rejected']


def test_structurally_missing_joint_conclusion_does_not_repurpose_bound_paper_cell():
    from services.deep_research.coverage_repair import prepare_coverage_repair

    cell = {'claimId':'cell', 'kind':'reported', 'text':'单篇论文的证据。', 'obligationIds':['joint']}
    joint = {'claimId':'joint-draft', 'kind':'inference', 'text':'尚未支持的比较结论。', 'obligationIds':['joint']}
    verification = {'accepted':[cell], 'rejected':[{'claimId':'joint-draft', 'reason':'semantic_unresolved'}]}
    audit = {'gaps':[{'obligationId':'joint', 'question':'比较两个条件', 'missingJointConclusion':True}],
             'verdicts':[{'obligationId':'joint', 'bindings':[{'claimId':'cell'}]}]}
    assert prepare_coverage_repair({'claims':[cell, joint]}, verification, audit,
                                   bound_comparison_targets=True) == verification
