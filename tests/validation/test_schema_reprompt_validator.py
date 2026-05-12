"""Tests for schema reprompt preflight warning in GranularityAndOutputFieldValidator."""

from agent_actions.validation.action_validators.granularity_output_field_validator import (
    GranularityAndOutputFieldValidator,
)
from agent_actions.validation.orchestration.action_entry_validation_orchestrator import (
    ActionEntryValidationContext,
)


def _make_context(entry: dict) -> ActionEntryValidationContext:
    return ActionEntryValidationContext(entry=entry, agent_name_context="test_workflow")


class TestSchemaRepromptWarning:
    """Tests for the schema reprompt preflight warning."""

    def test_warns_when_reprompt_and_schema_without_on_schema_mismatch(self):
        """Should warn when both reprompt and schema exist but on_schema_mismatch is missing."""
        entry = {
            "reprompt": {"validation": "check_fn", "max_attempts": 2},
            "schema": {"fields": [{"id": "x", "type": "string"}]},
        }
        result = GranularityAndOutputFieldValidator().validate(_make_context(entry))
        assert len(result.warnings) == 1
        assert "on_schema_mismatch" in result.warnings[0]
        assert len(result.errors) == 0

    def test_no_warning_when_on_schema_mismatch_set(self):
        """No warning when on_schema_mismatch is explicitly configured."""
        entry = {
            "reprompt": {"on_schema_mismatch": "reprompt", "max_attempts": 2},
            "schema": {"fields": [{"id": "x", "type": "string"}]},
        }
        result = GranularityAndOutputFieldValidator().validate(_make_context(entry))
        assert len(result.warnings) == 0
        assert len(result.errors) == 0

    def test_no_warning_when_no_schema(self):
        """No warning when reprompt exists but no schema."""
        entry = {
            "reprompt": {"validation": "check_fn", "max_attempts": 2},
        }
        result = GranularityAndOutputFieldValidator().validate(_make_context(entry))
        assert len(result.warnings) == 0

    def test_no_warning_when_no_reprompt(self):
        """No warning when schema exists but no reprompt."""
        entry = {
            "schema": {"fields": [{"id": "x", "type": "string"}]},
        }
        result = GranularityAndOutputFieldValidator().validate(_make_context(entry))
        assert len(result.warnings) == 0

    def test_no_warning_when_reprompt_is_not_dict(self):
        """No warning when reprompt is a non-dict value."""
        entry = {
            "reprompt": True,
            "schema": {"fields": [{"id": "x", "type": "string"}]},
        }
        result = GranularityAndOutputFieldValidator().validate(_make_context(entry))
        assert len(result.warnings) == 0

    def test_warns_with_schema_name_instead_of_schema(self):
        """Should warn when schema_name is used instead of inline schema."""
        entry = {
            "reprompt": {"validation": "check_fn"},
            "schema_name": "my_schema",
        }
        result = GranularityAndOutputFieldValidator().validate(_make_context(entry))
        assert len(result.warnings) == 1
        assert "on_schema_mismatch" in result.warnings[0]
