"""Offline tests for services.deep_research.hypothesis_spec."""

import copy
import json

import pytest

from services.deep_research.hypothesis_spec import (
    HYPOTHESIS_SPEC_CONTRACT,
    hypothesis_analysis_errors,
    render_hypothesis_spec,
    validate_hypothesis_spec,
)
from services.deep_research.execution_spec import execution_spec_errors


# --------------- helpers ---------------

def _valid_spec(**overrides):
    base = {
        "statement": "\u6761\u4ef6A\u5728B0\u6c34\u5e73\u4e0b\u4ea7\u751f\u6b63\u5411\u6548\u5e94",
        "analysisClaimId": "analysis-1",
        "effectKeys": ["A_cond_B0"],
        "purpose": "explore",
    }
    base.update(overrides)
    return base


def _valid_analysis_claim(**overrides):
    base = {
        "claimId": "analysis-1",
        "kind": "proposal",
        "designRole": "analysis",
        "executionSpec": {
            "effects": {"A_cond_B0": "mean(A1|B0) - mean(A0|B0)", "A_main": "mean(A1) - mean(A0)"},
            "uncertainty": {"mode": "descriptive", "boundary": "observed range"},
            "decision": {"mode": "descriptive", "boundary": "observed range"},
        },
    }
    base.update(overrides)
    return base


def _test_zero_analysis_claim(**overrides):
    base = {
        "claimId": "analysis-2",
        "kind": "proposal",
        "designRole": "analysis",
        "executionSpec": {
            "effects": {"A_main": "mean(A1) - mean(A0)"},
            "uncertainty": {
                "mode": "paired_cluster_bootstrap",
                "unit": "participant",
                "repetitions": 1000,
                "confidence": 0.95,
                "seed": 42,
            },
            "decision": {"mode": "interval_excludes_zero"},
        },
    }
    base.update(overrides)
    return base


def _equivalence_analysis_claim(**overrides):
    base = {
        "claimId": "analysis-3",
        "kind": "proposal",
        "designRole": "analysis",
        "executionSpec": {
            "effects": {"A_main": "mean(A1) - mean(A0)"},
            "uncertainty": {
                "mode": "analytic",
                "method": "two-one-sided t-test",
                "assumptions": ["normality"],
                "confidence": 0.95,
            },
            "decision": {"mode": "equivalence", "tolerances": {"A_main": 0.5}},
        },
    }
    base.update(overrides)
    return base


# --------------- validate_hypothesis_spec ---------------

class TestValidateHypothesisSpec:
    def test_valid_spec_no_errors(self):
        assert validate_hypothesis_spec(_valid_spec()) == []

    def test_missing_statement(self):
        spec = _valid_spec()
        del spec["statement"]
        errs = validate_hypothesis_spec(spec)
        assert "statement" in errs

    def test_missing_analysis_claim_id(self):
        spec = _valid_spec()
        del spec["analysisClaimId"]
        errs = validate_hypothesis_spec(spec)
        assert "analysisClaimId" in errs

    def test_missing_effect_keys(self):
        spec = _valid_spec()
        del spec["effectKeys"]
        errs = validate_hypothesis_spec(spec)
        assert "effectKeys" in errs

    def test_missing_purpose(self):
        spec = _valid_spec()
        del spec["purpose"]
        errs = validate_hypothesis_spec(spec)
        assert "purpose" in errs

    def test_extra_key_rejected(self):
        spec = _valid_spec(extra_field="oops")
        errs = validate_hypothesis_spec(spec)
        assert "extra_field" in errs

    def test_statement_blank(self):
        errs = validate_hypothesis_spec(_valid_spec(statement="   "))
        assert "statement" in errs

    def test_statement_not_string(self):
        errs = validate_hypothesis_spec(_valid_spec(statement=123))
        assert "statement" in errs

    def test_statement_bool(self):
        errs = validate_hypothesis_spec(_valid_spec(statement=True))
        assert "statement" in errs

    def test_analysis_claim_id_blank(self):
        errs = validate_hypothesis_spec(_valid_spec(analysisClaimId=""))
        assert "analysisClaimId" in errs

    def test_analysis_claim_id_int(self):
        errs = validate_hypothesis_spec(_valid_spec(analysisClaimId=42))
        assert "analysisClaimId" in errs

    def test_effect_keys_empty_list(self):
        errs = validate_hypothesis_spec(_valid_spec(effectKeys=[]))
        assert "effectKeys" in errs

    def test_effect_keys_not_list(self):
        errs = validate_hypothesis_spec(_valid_spec(effectKeys="A_main"))
        assert "effectKeys" in errs

    def test_effect_keys_contains_blank(self):
        errs = validate_hypothesis_spec(_valid_spec(effectKeys=["A_main", ""]))
        assert "effectKeys[1]" in errs

    def test_effect_keys_contains_int(self):
        errs = validate_hypothesis_spec(_valid_spec(effectKeys=[7]))
        assert "effectKeys[0]" in errs

    def test_effect_keys_contains_bool(self):
        errs = validate_hypothesis_spec(_valid_spec(effectKeys=[True]))
        assert "effectKeys[0]" in errs

    def test_effect_keys_contains_list_unhashable(self):
        errs = validate_hypothesis_spec(_valid_spec(effectKeys=[["nested"]]))
        assert "effectKeys[0]" in errs
        assert "effectKeys" in errs  # _all_unique fails on unhashable

    def test_effect_keys_duplicates(self):
        errs = validate_hypothesis_spec(_valid_spec(effectKeys=["A_main", "A_main"]))
        assert "effectKeys" in errs

    def test_purpose_invalid_string(self):
        errs = validate_hypothesis_spec(_valid_spec(purpose="confirm"))
        assert "purpose" in errs

    def test_purpose_none(self):
        errs = validate_hypothesis_spec(_valid_spec(purpose=None))
        assert "purpose" in errs

    def test_purpose_bool_true(self):
        errs = validate_hypothesis_spec(_valid_spec(purpose=True))
        assert "purpose" in errs

    def test_purpose_list_unhashable(self):
        errs = validate_hypothesis_spec(_valid_spec(purpose=["explore"]))
        assert "purpose" in errs

    def test_purpose_dict_unhashable(self):
        errs = validate_hypothesis_spec(_valid_spec(purpose={"k": "v"}))
        assert "purpose" in errs

    def test_spec_not_dict_none(self):
        assert validate_hypothesis_spec(None) == ["spec"]

    def test_spec_not_dict_list(self):
        assert validate_hypothesis_spec([1, 2]) == ["spec"]

    def test_spec_not_dict_string(self):
        assert validate_hypothesis_spec("hello") == ["spec"]

    def test_all_valid_purposes(self):
        for p in ("explore", "test_zero", "assess_equivalence"):
            assert validate_hypothesis_spec(_valid_spec(purpose=p)) == []

    def test_no_mutation(self):
        spec = _valid_spec()
        snapshot = copy.deepcopy(spec)
        validate_hypothesis_spec(spec)
        assert spec == snapshot

    def test_stable_order(self):
        spec = _valid_spec()
        del spec["statement"]
        del spec["purpose"]
        e1 = validate_hypothesis_spec(spec)
        e2 = validate_hypothesis_spec(spec)
        assert e1 == e2


# --------------- render_hypothesis_spec ---------------

class TestRenderHypothesisSpec:
    def test_invalid_returns_empty(self):
        assert render_hypothesis_spec({}) == ""
        assert render_hypothesis_spec(None) == ""

    def test_label_present(self):
        text = render_hypothesis_spec(_valid_spec())
        assert "\u62df\u8bae\u5047\u8bbe\u4e0e\u5224\u65ad\u8303\u56f4\uff08\u5c1a\u672a\u9a8c\u8bc1\uff09" in text

    def test_statement_shown(self):
        text = render_hypothesis_spec(_valid_spec())
        assert "\u6761\u4ef6A\u5728B0\u6c34\u5e73\u4e0b\u4ea7\u751f\u6b63\u5411\u6548\u5e94" in text

    def test_standard_effect_label_mapped(self):
        text = render_hypothesis_spec(_valid_spec(effectKeys=["A_main"]))
        assert "A的平均主效应" in text

    def test_unknown_effect_key_shown_verbatim(self):
        text = render_hypothesis_spec(_valid_spec(effectKeys=["custom_metric"]))
        assert "custom_metric" in text

    def test_no_analysis_claim_id_in_output(self):
        text = render_hypothesis_spec(_valid_spec())
        assert "analysis-1" not in text

    def test_no_purpose_enum_in_output(self):
        for p in ("explore", "test_zero", "assess_equivalence"):
            text = render_hypothesis_spec(_valid_spec(purpose=p))
            assert p not in text

    def test_explore_mentions_no_verdict(self):
        text = render_hypothesis_spec(_valid_spec(purpose="explore"))
        assert "\u4e0d\u505a\u663e\u8457\u6027\u6216\u7b49\u4ef7\u6027\u5224\u5b9a" in text

    def test_test_zero_mentions_interval_rule(self):
        text = render_hypothesis_spec(_valid_spec(purpose="test_zero"))
        assert "\u7f6e\u4fe1\u533a\u95f4\u662f\u5426\u6392\u9664\u96f6" in text
        assert "\u975e\u663e\u8457\u7ed3\u679c\u4e0d\u7b49\u4e8e\u6548\u5e94\u4e0d\u5b58\u5728" in text

    def test_equivalence_mentions_tolerances(self):
        text = render_hypothesis_spec(_valid_spec(purpose="assess_equivalence"))
        assert "\u5bb9\u5dee\u8303\u56f4" in text
        assert "\u4e0d\u9884\u5148\u5ba3\u5e03\u7ed3\u679c" in text

    def test_statement_json_quoted(self):
        tricky = 'He said "hello" & <world>'
        text = render_hypothesis_spec(_valid_spec(statement=tricky))
        assert json.dumps(tricky, ensure_ascii=False) in text

    def test_no_invented_values(self):
        text = render_hypothesis_spec(_valid_spec())
        assert "p=" not in text
        assert "p <" not in text


# --------------- hypothesis_analysis_errors ---------------

class TestHypothesisAnalysisErrors:
    def test_valid_explore_linkage(self):
        spec = _valid_spec()
        claim = _valid_analysis_claim()
        assert hypothesis_analysis_errors(spec, claim) == []

    def test_valid_test_zero_linkage(self):
        spec = _valid_spec(
            analysisClaimId="analysis-2",
            effectKeys=["A_main"],
            purpose="test_zero",
        )
        claim = _test_zero_analysis_claim()
        assert hypothesis_analysis_errors(spec, claim) == []

    def test_valid_equivalence_linkage(self):
        spec = _valid_spec(
            analysisClaimId="analysis-3",
            effectKeys=["A_main"],
            purpose="assess_equivalence",
        )
        claim = _equivalence_analysis_claim()
        assert hypothesis_analysis_errors(spec, claim) == []

    def test_invalid_own_spec_propagates(self):
        spec = _valid_spec()
        del spec["statement"]
        errs = hypothesis_analysis_errors(spec, _valid_analysis_claim())
        assert "spec.statement" in errs

    def test_analysis_claim_not_dict(self):
        errs = hypothesis_analysis_errors(_valid_spec(), "not a dict")
        assert "analysis_claim" in errs

    def test_analysis_claim_none(self):
        errs = hypothesis_analysis_errors(_valid_spec(), None)
        assert "analysis_claim" in errs

    def test_wrong_claim_id(self):
        claim = _valid_analysis_claim(claimId="wrong-id")
        errs = hypothesis_analysis_errors(_valid_spec(), claim)
        assert "analysis_claim.claimId" in errs

    def test_missing_claim_id(self):
        claim = _valid_analysis_claim()
        del claim["claimId"]
        errs = hypothesis_analysis_errors(_valid_spec(), claim)
        assert "analysis_claim.claimId" in errs

    def test_invalid_kind(self):
        claim = _valid_analysis_claim(kind="experiment")
        errs = hypothesis_analysis_errors(_valid_spec(), claim)
        assert "analysis_claim.kind" in errs

    def test_valid_kinds_accepted(self):
        for k in ("proposal", "suggestion", "hypothesis"):
            claim = _valid_analysis_claim(kind=k)
            errs = hypothesis_analysis_errors(_valid_spec(), claim)
            assert "analysis_claim.kind" not in errs

    def test_wrong_design_role(self):
        claim = _valid_analysis_claim(designRole="data")
        errs = hypothesis_analysis_errors(_valid_spec(), claim)
        assert "analysis_claim.designRole" in errs

    def test_missing_design_role(self):
        claim = _valid_analysis_claim()
        del claim["designRole"]
        errs = hypothesis_analysis_errors(_valid_spec(), claim)
        assert "analysis_claim.designRole" in errs

    def test_malformed_execution_spec_propagates(self):
        claim = _valid_analysis_claim(executionSpec="garbage")
        errs = hypothesis_analysis_errors(_valid_spec(), claim)
        assert any("executionSpec" in e for e in errs)

    def test_missing_execution_spec(self):
        claim = _valid_analysis_claim()
        del claim["executionSpec"]
        errs = hypothesis_analysis_errors(_valid_spec(), claim)
        assert any("executionSpec" in e for e in errs)

    def test_effect_key_not_in_analysis_effects(self):
        spec = _valid_spec(effectKeys=["nonexistent_key"])
        claim = _valid_analysis_claim()
        errs = hypothesis_analysis_errors(spec, claim)
        assert "effectKeys.nonexistent_key" in errs

    def test_all_effect_keys_present(self):
        spec = _valid_spec(effectKeys=["A_cond_B0", "A_main"])
        claim = _valid_analysis_claim()
        errs = hypothesis_analysis_errors(spec, claim)
        assert errs == []

    def test_test_zero_linked_to_descriptive_rejected(self):
        spec = _valid_spec(
            analysisClaimId="analysis-1",
            effectKeys=["A_cond_B0"],
            purpose="test_zero",
        )
        claim = _valid_analysis_claim()  # decision mode is descriptive
        errs = hypothesis_analysis_errors(spec, claim)
        assert "purpose_decision_mismatch" in errs

    def test_equivalence_linked_to_descriptive_rejected(self):
        spec = _valid_spec(
            analysisClaimId="analysis-1",
            effectKeys=["A_cond_B0"],
            purpose="assess_equivalence",
        )
        claim = _valid_analysis_claim()
        errs = hypothesis_analysis_errors(spec, claim)
        assert "purpose_decision_mismatch" in errs

    def test_explore_linked_to_interval_rejected(self):
        spec = _valid_spec(
            analysisClaimId="analysis-2",
            effectKeys=["A_main"],
            purpose="explore",
        )
        claim = _test_zero_analysis_claim()
        errs = hypothesis_analysis_errors(spec, claim)
        assert "purpose_decision_mismatch" in errs

    def test_equivalence_without_tolerances_uses_existing_validator(self):
        exec_spec = {
            "effects": {"A_main": "mean(A1) - mean(A0)"},
            "uncertainty": {
                "mode": "analytic",
                "method": "tost",
                "assumptions": ["normality"],
                "confidence": 0.95,
            },
            "decision": {"mode": "equivalence"},
        }
        existing = execution_spec_errors("analysis", exec_spec)
        assert any("tolerances" in e for e in existing)

        claim = _valid_analysis_claim(
            claimId="analysis-3",
            executionSpec=exec_spec,
        )
        spec = _valid_spec(
            analysisClaimId="analysis-3",
            effectKeys=["A_main"],
            purpose="assess_equivalence",
        )
        errs = hypothesis_analysis_errors(spec, claim)
        assert any("tolerances" in e for e in errs)

    def test_explore_with_bootstrap_uncertainty_descriptive_decision(self):
        exec_spec = {
            "effects": {"A_main": "mean(A1) - mean(A0)"},
            "uncertainty": {
                "mode": "paired_cluster_bootstrap",
                "unit": "participant",
                "repetitions": 500,
                "confidence": 0.95,
                "seed": 7,
            },
            "decision": {"mode": "descriptive", "boundary": "95% CI"},
        }
        claim = _valid_analysis_claim(executionSpec=exec_spec)
        spec = _valid_spec(effectKeys=["A_main"], purpose="explore")
        errs = hypothesis_analysis_errors(spec, claim)
        assert errs == []

    def test_no_mutation_spec(self):
        spec = _valid_spec()
        claim = _valid_analysis_claim()
        spec_snap = copy.deepcopy(spec)
        claim_snap = copy.deepcopy(claim)
        hypothesis_analysis_errors(spec, claim)
        assert spec == spec_snap
        assert claim == claim_snap

    def test_no_mutation_on_error_path(self):
        spec = _valid_spec()
        claim = _valid_analysis_claim(claimId="wrong")
        spec_snap = copy.deepcopy(spec)
        claim_snap = copy.deepcopy(claim)
        hypothesis_analysis_errors(spec, claim)
        assert spec == spec_snap
        assert claim == claim_snap

    def test_stable_error_order(self):
        spec = _valid_spec(effectKeys=["missing1", "missing2"])
        claim = _valid_analysis_claim(claimId="wrong", kind="bad")
        e1 = hypothesis_analysis_errors(spec, claim)
        e2 = hypothesis_analysis_errors(spec, claim)
        assert e1 == e2

    def test_scientific_limit_no_validity_judgment(self):
        """The module checks typed linkage, not scientific correctness."""
        spec = _valid_spec(
            statement="\u5b87\u5b99\u4e2d\u5b58\u5728\u672a\u77e5\u529b\u91cf\u5f71\u54cd\u5b9e\u9a8c",
        )
        claim = _valid_analysis_claim()
        errs = hypothesis_analysis_errors(spec, claim)
        assert errs == []

    def test_does_not_select_alternative_analysis(self):
        """Wrong ID is an error; no fallback to another analysis."""
        spec = _valid_spec(analysisClaimId="nonexistent")
        claim = _valid_analysis_claim(claimId="analysis-1")
        errs = hypothesis_analysis_errors(spec, claim)
        assert "analysis_claim.claimId" in errs


# --------------- contract constant ---------------

class TestContractConstant:
    def test_is_nonempty_string(self):
        assert isinstance(HYPOTHESIS_SPEC_CONTRACT, str)
        assert len(HYPOTHESIS_SPEC_CONTRACT) > 0
