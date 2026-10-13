"""Tests for services/deep_research/budget_spec.py."""

import copy
import math

import pytest

from services.deep_research.budget_spec import (
    BUDGET_SPEC_CONTRACT,
    validate_budget_spec,
    render_budget_spec,
    budget_group_errors,
)


# --- helpers ---


def _valid_train_baseline():
    return {
        "mode": "train",
        "unit": "optimizer_steps",
        "maxBudget": 1000,
        "stoppingRule": "early stop on plateau",
    }


def _valid_existing_baseline():
    return {
        "mode": "existing",
        "selectionRule": "select best checkpoint by validation loss",
    }


def _matched_groups(width=2, value=100):
    return {format(i, f"0{width}b"): value for i in range(2 ** width)}


def _valid_matched_spec(value=100):
    return {
        "baseline": _valid_train_baseline(),
        "recovery": {
            "mode": "matched",
            "unit": "optimizer_steps",
            "groups": _matched_groups(value=value),
        },
    }


def _valid_unmatched_spec():
    return {
        "baseline": _valid_train_baseline(),
        "recovery": {
            "mode": "unmatched",
            "unit": "optimizer_steps",
            "groups": {"00": 0, "01": 500, "10": 1000, "11": 1500},
            "note": "Budget confounding: groups differ in compute.",
        },
    }


def _group_spec_2factors():
    return {
        "factors": [
            {
                "name": "lr",
                "control": {
                    "action": "set",
                    "parameters": [
                        {"name": "lr", "type": "number", "value": 0.01}
                    ],
                },
                "treatment": {
                    "action": "set",
                    "parameters": [
                        {"name": "lr", "type": "number", "value": 0.001}
                    ],
                },
            },
            {
                "name": "dropout",
                "control": {
                    "action": "set",
                    "parameters": [
                        {"name": "dropout", "type": "number", "value": 0.0}
                    ],
                },
                "treatment": {
                    "action": "set",
                    "parameters": [
                        {"name": "dropout", "type": "number", "value": 0.5}
                    ],
                },
            },
        ]
    }


def _group_spec_1factor():
    return {
        "factors": [
            {
                "name": "lr",
                "control": {
                    "action": "set",
                    "parameters": [
                        {"name": "lr", "type": "number", "value": 0.01}
                    ],
                },
                "treatment": {
                    "action": "set",
                    "parameters": [
                        {"name": "lr", "type": "number", "value": 0.001}
                    ],
                },
            },
        ]
    }


# --- BUDGET_SPEC_CONTRACT ---


class TestContract:
    def test_contract_is_nonempty_string(self):
        assert isinstance(BUDGET_SPEC_CONTRACT, str)
        assert len(BUDGET_SPEC_CONTRACT) > 0


# --- valid specs ---


class TestValidateValid:
    def test_matched_all_zero(self):
        assert validate_budget_spec(_valid_matched_spec(value=0)) == []

    def test_matched_equal_nonzero(self):
        assert validate_budget_spec(_valid_matched_spec(value=500)) == []

    def test_unmatched_valid_with_note(self):
        assert validate_budget_spec(_valid_unmatched_spec()) == []

    def test_baseline_train(self):
        assert validate_budget_spec(_valid_matched_spec()) == []

    def test_baseline_existing(self):
        spec = _valid_matched_spec()
        spec["baseline"] = _valid_existing_baseline()
        assert validate_budget_spec(spec) == []

    def test_wall_seconds_float_budget(self):
        spec = _valid_matched_spec()
        spec["baseline"]["unit"] = "wall_seconds"
        spec["baseline"]["maxBudget"] = 3600.5
        spec["recovery"]["unit"] = "wall_seconds"
        spec["recovery"]["groups"] = {
            "00": 100.5, "01": 100.5, "10": 100.5, "11": 100.5
        }
        assert validate_budget_spec(spec) == []

    def test_epochs_int_budget(self):
        spec = _valid_matched_spec()
        spec["baseline"]["unit"] = "epochs"
        spec["baseline"]["maxBudget"] = 50
        spec["recovery"]["unit"] = "epochs"
        spec["recovery"]["groups"] = {"00": 10, "01": 10, "10": 10, "11": 10}
        assert validate_budget_spec(spec) == []


# --- matched unequal rejection ---


class TestMatchedUnequal:
    def test_zero_vs_others_rejected(self):
        spec = _valid_matched_spec()
        spec["recovery"]["groups"] = {
            "00": 0, "01": 1000, "10": 1000, "11": 1000
        }
        errors = validate_budget_spec(spec)
        assert len(errors) > 0
        assert any("相等" in e for e in errors)


# --- malformed types ---


class TestMalformedTypes:
    def test_spec_not_dict(self):
        for bad in (None, 42, "str", [], True):
            assert validate_budget_spec(bad) != []

    def test_bool_maxbudget(self):
        spec = _valid_matched_spec()
        spec["baseline"]["maxBudget"] = True
        assert validate_budget_spec(spec) != []

    def test_nan_maxbudget(self):
        spec = _valid_matched_spec()
        spec["baseline"]["maxBudget"] = float("nan")
        assert validate_budget_spec(spec) != []

    def test_inf_maxbudget(self):
        spec = _valid_matched_spec()
        spec["baseline"]["maxBudget"] = float("inf")
        assert validate_budget_spec(spec) != []

    def test_negative_maxbudget(self):
        spec = _valid_matched_spec()
        spec["baseline"]["maxBudget"] = -1
        assert validate_budget_spec(spec) != []

    def test_zero_maxbudget(self):
        spec = _valid_matched_spec()
        spec["baseline"]["maxBudget"] = 0
        assert validate_budget_spec(spec) != []

    def test_float_maxbudget_for_steps(self):
        spec = _valid_matched_spec()
        spec["baseline"]["maxBudget"] = 100.5
        assert validate_budget_spec(spec) != []

    def test_bool_group_value(self):
        spec = _valid_matched_spec()
        spec["recovery"]["groups"] = {
            "00": True, "01": True, "10": True, "11": True
        }
        assert validate_budget_spec(spec) != []

    def test_nan_group_value(self):
        spec = _valid_matched_spec()
        spec["recovery"]["groups"] = {
            "00": float("nan"), "01": float("nan"),
            "10": float("nan"), "11": float("nan"),
        }
        assert validate_budget_spec(spec) != []

    def test_inf_group_value(self):
        spec = _valid_matched_spec()
        spec["recovery"]["groups"] = {
            "00": float("inf"), "01": float("inf"),
            "10": float("inf"), "11": float("inf"),
        }
        assert validate_budget_spec(spec) != []

    def test_negative_group_value(self):
        spec = _valid_matched_spec()
        spec["recovery"]["groups"] = {"00": -1, "01": -1, "10": -1, "11": -1}
        assert validate_budget_spec(spec) != []

    def test_float_group_value_for_steps(self):
        spec = _valid_matched_spec()
        spec["recovery"]["groups"] = {
            "00": 1.5, "01": 1.5, "10": 1.5, "11": 1.5
        }
        assert validate_budget_spec(spec) != []


# --- group membership and widths ---


class TestGroupMembership:
    def test_incomplete_binary_set(self):
        spec = _valid_matched_spec()
        spec["recovery"]["groups"] = {"00": 100, "01": 100, "10": 100}
        assert validate_budget_spec(spec) != []

    def test_mixed_widths(self):
        spec = _valid_matched_spec()
        spec["recovery"]["groups"] = {
            "0": 100, "01": 100, "10": 100, "11": 100
        }
        assert validate_budget_spec(spec) != []

    def test_single_group_rejected(self):
        spec = _valid_matched_spec()
        spec["recovery"]["groups"] = {"0": 100}
        assert validate_budget_spec(spec) != []

    def test_non_binary_key(self):
        spec = _valid_matched_spec()
        spec["recovery"]["groups"] = {
            "02": 100, "01": 100, "10": 100, "11": 100
        }
        assert validate_budget_spec(spec) != []

    def test_empty_groups(self):
        spec = _valid_matched_spec()
        spec["recovery"]["groups"] = {}
        assert validate_budget_spec(spec) != []

    def test_width_1_complete_set(self):
        spec = _valid_matched_spec()
        spec["recovery"]["groups"] = {"0": 50, "1": 50}
        assert validate_budget_spec(spec) == []


# --- extra / missing keys ---


class TestExtraMissingKeys:
    def test_extra_top_key(self):
        spec = _valid_matched_spec()
        spec["extra"] = "bad"
        assert validate_budget_spec(spec) != []

    def test_missing_baseline(self):
        spec = _valid_matched_spec()
        del spec["baseline"]
        assert validate_budget_spec(spec) != []

    def test_missing_recovery(self):
        spec = _valid_matched_spec()
        del spec["recovery"]
        assert validate_budget_spec(spec) != []

    def test_extra_baseline_key(self):
        spec = _valid_matched_spec()
        spec["baseline"]["extra"] = "bad"
        assert validate_budget_spec(spec) != []

    def test_missing_stopping_rule(self):
        spec = _valid_matched_spec()
        del spec["baseline"]["stoppingRule"]
        assert validate_budget_spec(spec) != []

    def test_extra_recovery_key_matched(self):
        spec = _valid_matched_spec()
        spec["recovery"]["extra"] = "bad"
        assert validate_budget_spec(spec) != []

    def test_unmatched_missing_note(self):
        spec = _valid_unmatched_spec()
        del spec["recovery"]["note"]
        assert validate_budget_spec(spec) != []

    def test_unmatched_blank_note(self):
        spec = _valid_unmatched_spec()
        spec["recovery"]["note"] = "   "
        assert validate_budget_spec(spec) != []

    def test_matched_with_note_is_extra_key(self):
        spec = _valid_matched_spec()
        spec["recovery"]["note"] = "should not be here"
        assert validate_budget_spec(spec) != []


# --- immutability ---


class TestImmutability:
    def test_validate_does_not_mutate_valid(self):
        spec = _valid_matched_spec()
        original = copy.deepcopy(spec)
        validate_budget_spec(spec)
        assert spec == original

    def test_validate_does_not_mutate_invalid(self):
        spec = {"bad": True}
        original = copy.deepcopy(spec)
        validate_budget_spec(spec)
        assert spec == original

    def test_render_does_not_mutate(self):
        spec = _valid_matched_spec()
        original = copy.deepcopy(spec)
        render_budget_spec(spec)
        assert spec == original


# --- render_budget_spec ---


class TestRender:
    def test_render_valid_matched(self):
        result = render_budget_spec(_valid_matched_spec(value=200))
        assert result != ""
        assert "拟议" in result
        assert "200" in result
        assert "00" in result
        assert "11" in result

    def test_render_unmatched_warns(self):
        result = render_budget_spec(_valid_unmatched_spec())
        assert result != ""
        assert "混淆" in result

    def test_render_invalid_returns_empty(self):
        assert render_budget_spec({"bad": True}) == ""
        assert render_budget_spec(None) == ""
        assert render_budget_spec("string") == ""

    def test_render_existing_baseline(self):
        spec = _valid_matched_spec()
        spec["baseline"] = _valid_existing_baseline()
        result = render_budget_spec(spec)
        assert result != ""
        assert "选择规则" in result

    def test_render_labels_unit(self):
        result = render_budget_spec(_valid_matched_spec())
        assert "优化步" in result and "optimizer_steps" not in result

    def test_render_each_group(self):
        spec = _valid_matched_spec(value=42)
        result = render_budget_spec(spec)
        for gid in ("00", "01", "10", "11"):
            assert gid in result


# --- budget_group_errors ---


class TestBudgetGroupErrors:
    def test_valid_2_factors_width_2(self):
        bs = _valid_matched_spec()
        gs = _group_spec_2factors()
        assert budget_group_errors(bs, gs) == []

    def test_mismatch_1_factor_vs_width_2(self):
        bs = _valid_matched_spec()
        gs = _group_spec_1factor()
        errors = budget_group_errors(bs, gs)
        assert len(errors) > 0
        assert any("不匹配" in e for e in errors)

    def test_invalid_budget_spec_returns_errors(self):
        errors = budget_group_errors({"bad": True}, _group_spec_2factors())
        assert len(errors) > 0

    def test_invalid_group_spec_returns_errors(self):
        errors = budget_group_errors(_valid_matched_spec(), {"factors": []})
        assert len(errors) > 0

    def test_both_invalid(self):
        errors = budget_group_errors({"x": 1}, {"y": 2})
        assert len(errors) > 0

    def test_width_1_matches_1_factor(self):
        bs = _valid_matched_spec()
        bs["recovery"]["groups"] = {"0": 10, "1": 10}
        gs = _group_spec_1factor()
        assert budget_group_errors(bs, gs) == []
