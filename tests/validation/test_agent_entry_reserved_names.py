"""Tests for reserved agent name validation in agent entries."""

from agent_actions.validation.agent_validators.agent_type_specific_validator import (
    AgentTypeSpecificValidator,
)
from agent_actions.validation.orchestration.agent_entry_validation_orchestrator import (
    AgentEntryValidationContext,
)


class TestAgentEntryReservedNames:
    """Ensure reserved names are rejected in agent entries."""

    def test_reserved_name_rejected(self):
        """Reserved names should raise validation errors."""
        context = AgentEntryValidationContext(
            entry={"name": "context_scope", "agent_type": "llm"},
            agent_name_context="test_agent",
        )
        validator = AgentTypeSpecificValidator()
        result = validator.validate(context)

        assert result.errors
        assert "reserved" in result.errors[0]
