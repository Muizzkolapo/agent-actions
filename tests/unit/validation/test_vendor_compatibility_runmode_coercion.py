"""Tests for VendorCompatibilityValidator RunMode boundary coercion."""

from agent_actions.config.types import RunMode
from agent_actions.validation.action_validators.vendor_compatibility_validator import (
    VendorCompatibilityValidator,
)
from agent_actions.validation.orchestration.action_entry_validation_orchestrator import (
    ActionEntryValidationContext,
)


class TestRunModeCoercion:
    """Verify RunMode string coercion at the validator boundary."""

    def test_uppercase_string_batch_coerced_and_validates(self):
        """String 'BATCH' is coerced to RunMode.BATCH; valid vendor passes."""
        context = ActionEntryValidationContext(
            entry={"run_mode": "BATCH", "model_vendor": "openai"},
            agent_name_context="test_agent",
        )
        validator = VendorCompatibilityValidator()
        result = validator.validate(context)
        assert not result.errors

    def test_lowercase_string_batch_coerced_and_validates(self):
        """String 'batch' is coerced to RunMode.BATCH; valid vendor passes."""
        context = ActionEntryValidationContext(
            entry={"run_mode": "batch", "model_vendor": "anthropic"},
            agent_name_context="test_agent",
        )
        validator = VendorCompatibilityValidator()
        result = validator.validate(context)
        assert not result.errors

    def test_enum_passthrough_batch(self):
        """RunMode.BATCH enum value passes through without coercion."""
        context = ActionEntryValidationContext(
            entry={"run_mode": RunMode.BATCH, "model_vendor": "openai"},
            agent_name_context="test_agent",
        )
        validator = VendorCompatibilityValidator()
        result = validator.validate(context)
        assert not result.errors

    def test_online_mode_skips_batch_validation(self):
        """Online mode skips batch vendor checks entirely."""
        context = ActionEntryValidationContext(
            entry={"run_mode": "ONLINE", "model_vendor": "tool"},
            agent_name_context="test_agent",
        )
        validator = VendorCompatibilityValidator()
        result = validator.validate(context)
        assert not result.errors

    def test_batch_unknown_vendor_produces_warning(self):
        """Batch mode with unknown (but non-tool) vendor emits a warning, not an error."""
        context = ActionEntryValidationContext(
            entry={"run_mode": "BATCH", "model_vendor": "some_unknown_vendor"},
            agent_name_context="test_agent",
        )
        validator = VendorCompatibilityValidator()
        result = validator.validate(context)
        assert not result.errors
        assert result.warnings
        assert "some_unknown_vendor" in result.warnings[0]


class TestBatchKindValidation:
    """Batch mode for each action kind; tool and hitl cases live in test_tool_and_hitl_actions_run_online_in_a_batch_run.py."""

    def test_online_kind_tool_passes(self):
        """Online mode with kind=tool produces no errors (valid config)."""
        context = ActionEntryValidationContext(
            entry={"run_mode": "online", "kind": "tool"},
            agent_name_context="test_agent",
        )
        validator = VendorCompatibilityValidator()
        result = validator.validate(context)
        assert not result.errors

    def test_batch_kind_llm_passes(self):
        """Batch mode with kind=llm and valid vendor produces no errors."""
        context = ActionEntryValidationContext(
            entry={"run_mode": "batch", "kind": "llm", "model_vendor": "openai"},
            agent_name_context="test_agent",
        )
        validator = VendorCompatibilityValidator()
        result = validator.validate(context)
        assert not result.errors
