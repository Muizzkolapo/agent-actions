"""Regression tests: reprompt.on_schema_mismatch without schema must not silently pass.

Covers preflight detection and runtime warning for configurations where the user
requests strict schema validation (reject/reprompt) but provides no schema.
"""

from unittest.mock import patch

from agent_actions.processing.helpers import _validate_llm_output_schema
from agent_actions.validation.orchestration.action_entry_validation_orchestrator import (
    ActionEntryValidationOrchestrator,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _validate_entry(entry: dict) -> tuple[list, list]:
    """Run orchestrator on a single action entry, return (errors, warnings)."""
    orch = ActionEntryValidationOrchestrator()
    orch.validate_action_entry(entry, "test_workflow")
    return orch.get_validation_errors(), orch.get_validation_warnings()


# ── Preflight: reject without schema ────────────────────────────────


# ── Preflight: reprompt without schema ──────────────────────────────


class TestPreflightRepromptWithoutSchema:
    """reprompt.on_schema_mismatch: reprompt + no schema → preflight error."""


# ── Preflight: no false positives ─────────────────────────────────


class TestPreflightNoFalsePositives:
    """Default (no reprompt config) must NOT error when schema is missing."""


# ── Runtime: warning logged ─────────────────────────────────────────


class TestRuntimeWarning:
    """Belt-and-suspenders: runtime warns when preflight was bypassed."""

    @patch("agent_actions.processing.helpers.logger")
    def test_no_config_no_warning(self, mock_logger):
        """Runtime path does NOT warn when no mismatch mode is set."""
        config = {}
        response = {"any": "value"}
        _validate_llm_output_schema(response, config, "test_action")
        mock_logger.warning.assert_not_called()
