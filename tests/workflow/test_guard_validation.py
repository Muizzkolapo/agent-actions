"""Unit tests for validate_guard_conditions() — all 6 branches."""

import pytest

from agent_actions.validation.preflight.guard_validation import validate_guard_conditions


class TestValidateGuardConditions:
    """Tests for the module-level validate_guard_conditions helper."""

    @pytest.mark.parametrize(
        "action_config",
        [
            pytest.param({"model": "gpt-4"}, id="no_guard_key"),
            pytest.param({"guard": None}, id="guard_is_none"),
            pytest.param({"guard": "passes_filter"}, id="guard_not_dict"),
            pytest.param(
                {"guard": {"scope": "item", "behavior": "filter"}}, id="guard_dict_missing_clause"
            ),
            pytest.param({"guard": {"clause": "", "scope": "item"}}, id="guard_dict_empty_clause"),
        ],
    )
    def test_guard_without_a_clause_is_skipped(self, action_config):
        assert validate_guard_conditions({"action_a": action_config}) == []

    def test_valid_clause_produces_no_errors(self):
        """Well-formed guard clause → no errors."""
        configs = {
            "select_for_users": {
                "guard": {
                    "clause": "source.passes_filter == true",
                    "scope": "item",
                    "behavior": "filter",
                }
            }
        }
        assert validate_guard_conditions(configs) == []

    def test_invalid_clause_produces_error(self):
        """Unparseable clause → one error entry with action name and clause in message."""
        configs = {
            "broken_action": {
                "guard": {"clause": "passes_filter ==", "scope": "item", "behavior": "filter"}
            }
        }
        errors = validate_guard_conditions(configs)
        assert len(errors) == 1
        assert "broken_action" in errors[0]
        assert "passes_filter ==" in errors[0]

    def test_multiple_actions_collects_all_errors(self):
        """Multiple invalid guards → all errors collected, not stopped at first."""
        configs = {
            "action_a": {"guard": {"clause": "a ==", "scope": "item"}},
            "action_b": {"guard": {"clause": "source.score > 0", "scope": "item"}},
            "action_c": {"guard": {"clause": "b ==", "scope": "item"}},
        }
        errors = validate_guard_conditions(configs)
        assert len(errors) == 2
        action_names = " ".join(errors)
        assert "action_a" in action_names
        assert "action_c" in action_names
        assert "action_b" not in action_names  # valid clause

    def test_empty_action_configs(self):
        """No actions → no errors."""
        assert validate_guard_conditions({}) == []
