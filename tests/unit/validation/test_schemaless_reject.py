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


def _base_entry(on_schema_mismatch=None, **overrides) -> dict:
    """Minimal LLM action entry with overrides.

    on_schema_mismatch is placed inside the reprompt dict.
    """
    entry = {
        "name": "test_action",
        "agent_type": "llm",
        "model_name": "gpt-4",
    }
    if on_schema_mismatch:
        reprompt = entry.get("reprompt", {})
        if isinstance(overrides.get("reprompt"), dict):
            reprompt = overrides.pop("reprompt")
        reprompt["on_schema_mismatch"] = on_schema_mismatch
        entry["reprompt"] = reprompt
    entry.update(overrides)
    return entry


# ── Preflight: reject without schema ────────────────────────────────


class TestPreflightRejectWithoutSchema:
    """reprompt.on_schema_mismatch: reject + no schema → preflight error."""

    def test_reject_no_schema_produces_actionable_error(self):
        """Reject mode without schema is caught with an actionable message."""
        errors, _ = _validate_entry(_base_entry(on_schema_mismatch="reject"))
        mismatch_errors = [e for e in errors if "on_schema_mismatch" in e.lower()]
        assert len(mismatch_errors) > 0, f"Expected schema-related error, got: {errors}"
        assert any(
            "schema" in e.lower() and ("define" in e.lower() or "requires" in e.lower())
            for e in mismatch_errors
        )

    def test_reject_with_inline_schema_passes(self):
        """Reject mode with inline schema does not trigger schema-missing error."""
        errors, _ = _validate_entry(
            _base_entry(
                on_schema_mismatch="reject",
                schema={"summary": "string", "score": "number"},
            )
        )
        schema_errors = [
            e
            for e in errors
            if "on_schema_mismatch" in e.lower() and "requires a schema" in e.lower()
        ]
        assert len(schema_errors) == 0

    def test_reject_with_schema_name_passes(self):
        """Reject mode with schema_name does not trigger schema-missing error."""
        errors, _ = _validate_entry(
            _base_entry(on_schema_mismatch="reject", schema_name="my_schema")
        )
        schema_errors = [
            e
            for e in errors
            if "on_schema_mismatch" in e.lower() and "requires a schema" in e.lower()
        ]
        assert len(schema_errors) == 0


# ── Preflight: reprompt without schema ──────────────────────────────


class TestPreflightRepromptWithoutSchema:
    """reprompt.on_schema_mismatch: reprompt + no schema → preflight error."""

    def test_reprompt_no_schema_produces_error(self):
        """Reprompt mode without schema is caught."""
        errors, _ = _validate_entry(_base_entry(on_schema_mismatch="reprompt"))
        assert any("requires a schema" in e.lower() for e in errors), (
            f"Expected schema-required error, got: {errors}"
        )

    def test_reprompt_with_schema_and_config_passes(self):
        """Reprompt mode with schema + reprompt block has no schema-missing error."""
        entry = {
            "name": "test_action",
            "agent_type": "llm",
            "model_name": "gpt-4",
            "reprompt": {
                "on_schema_mismatch": "reprompt",
                "validation": "my_validator",
            },
            "schema": {"summary": "string"},
        }
        errors, _ = _validate_entry(entry)
        schema_errors = [e for e in errors if "requires a schema" in e.lower()]
        assert len(schema_errors) == 0


# ── Preflight: no false positives ─────────────────────────────────


class TestPreflightNoFalsePositives:
    """Default (no reprompt config) must NOT error when schema is missing."""

    def test_default_no_schema_no_error(self):
        """No reprompt config + no schema → no on_schema_mismatch error."""
        errors, _ = _validate_entry(_base_entry())
        mismatch_errors = [e for e in errors if "on_schema_mismatch" in e.lower()]
        assert len(mismatch_errors) == 0


# ── Runtime: warning logged ─────────────────────────────────────────


class TestRuntimeWarning:
    """Belt-and-suspenders: runtime warns when preflight was bypassed."""

    @patch("agent_actions.processing.helpers.logger")
    def test_reject_no_schema_logs_warning(self, mock_logger):
        """Runtime path logs warning when reject is set but no schema."""
        config = {"reprompt": {"on_schema_mismatch": "reject"}}
        response = {"any": "value"}
        result = _validate_llm_output_schema(response, config, "test_action")
        assert result == response  # passes through (no schema to validate)
        mock_logger.warning.assert_called_once()
        msg = mock_logger.warning.call_args[0][0]
        assert "no schema is defined" in msg

    @patch("agent_actions.processing.helpers.logger")
    def test_reprompt_no_schema_logs_warning(self, mock_logger):
        """Runtime path logs warning when reprompt is set but no schema."""
        config = {"reprompt": {"on_schema_mismatch": "reprompt"}}
        response = {"any": "value"}
        result = _validate_llm_output_schema(response, config, "test_action")
        assert result == response
        mock_logger.warning.assert_called_once()
        msg = mock_logger.warning.call_args[0][0]
        assert "no schema is defined" in msg

    @patch("agent_actions.processing.helpers.logger")
    def test_no_config_no_warning(self, mock_logger):
        """Runtime path does NOT warn when no mismatch mode is set."""
        config = {}
        response = {"any": "value"}
        _validate_llm_output_schema(response, config, "test_action")
        mock_logger.warning.assert_not_called()
