"""Unit tests for validate_guard_conditions() — all 6 branches."""

from agent_actions.workflow.coordinator import validate_guard_conditions


class TestValidateGuardConditions:
    """Tests for the module-level validate_guard_conditions helper."""

    def test_no_guard_key(self):
        """Action with no guard at all → no errors."""
        configs = {"action_a": {"model": "gpt-4"}}
        assert validate_guard_conditions(configs) == []

    def test_guard_is_none(self):
        """guard: null/None → skipped, no error."""
        configs = {"action_a": {"guard": None}}
        assert validate_guard_conditions(configs) == []

    def test_guard_not_dict(self):
        """guard as a non-dict value (e.g. leftover string) → skipped, no error."""
        configs = {"action_a": {"guard": "passes_filter"}}
        assert validate_guard_conditions(configs) == []

    def test_guard_dict_missing_clause(self):
        """guard dict with no 'clause' key → skipped, no error."""
        configs = {"action_a": {"guard": {"scope": "item", "behavior": "filter"}}}
        assert validate_guard_conditions(configs) == []

    def test_guard_dict_empty_clause(self):
        """guard dict with empty clause string → skipped, no error."""
        configs = {"action_a": {"guard": {"clause": "", "scope": "item"}}}
        assert validate_guard_conditions(configs) == []

    def test_valid_clause_produces_no_errors(self):
        """Well-formed guard clause → no errors."""
        configs = {
            "select_for_users": {
                "guard": {"clause": "passes_filter == true", "scope": "item", "behavior": "filter"}
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
            "action_b": {"guard": {"clause": "score > 0", "scope": "item"}},
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
