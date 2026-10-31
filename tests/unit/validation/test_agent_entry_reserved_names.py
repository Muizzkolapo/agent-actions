"""Tests for reserved agent name validation in agent entries."""

from agent_actions.validation.action_validators.action_type_specific_validator import (
    ActionTypeSpecificValidator,
)
from agent_actions.validation.orchestration.action_entry_validation_orchestrator import (
    ActionEntryValidationContext,
)


class TestAgentEntryReservedNames:
    """Ensure reserved names are rejected in agent entries."""

    def test_reserved_name_rejected(self):
        """Reserved names should raise validation errors."""
        context = ActionEntryValidationContext(
            entry={"name": "context_scope", "agent_type": "llm"},
            agent_name_context="test_agent",
        )
        validator = ActionTypeSpecificValidator()
        result = validator.validate(context)

        assert result.errors
        assert "reserved" in result.errors[0]
