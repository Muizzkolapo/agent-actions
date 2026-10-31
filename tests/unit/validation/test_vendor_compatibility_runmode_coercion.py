"""Tests for VendorCompatibilityValidator RunMode boundary coercion."""

import pytest

from agent_actions.config.types import RunMode
from agent_actions.validation.action_validators.vendor_compatibility_validator import (
    VendorCompatibilityValidator,
)
from agent_actions.validation.orchestration.action_entry_validation_orchestrator import (
    ActionEntryValidationContext,
)


def _validate(entry):
    context = ActionEntryValidationContext(entry=entry, agent_name_context="test_agent")
    return VendorCompatibilityValidator().validate(context)


@pytest.mark.parametrize(
    "entry",
    [
        # a run_mode string is coerced to RunMode at the boundary
        pytest.param({"run_mode": "BATCH", "model_vendor": "openai"}, id="upper-BATCH"),
        pytest.param({"run_mode": "batch", "model_vendor": "anthropic"}, id="lower-batch"),
        pytest.param({"run_mode": RunMode.BATCH, "model_vendor": "openai"}, id="enum-batch"),
        # online skips the batch vendor checks entirely
        pytest.param({"run_mode": "ONLINE", "model_vendor": "tool"}, id="online-skips"),
        pytest.param({"run_mode": "online", "kind": "tool"}, id="online-tool"),
        pytest.param(
            {"run_mode": "batch", "kind": "llm", "model_vendor": "openai"}, id="batch-llm"
        ),
    ],
)
def test_valid_entry_produces_no_errors(entry):
    assert not _validate(entry).errors


def test_batch_unknown_vendor_produces_warning():
    """Batch mode with unknown (but non-tool) vendor emits a warning, not an error."""
    result = _validate({"run_mode": "BATCH", "model_vendor": "some_unknown_vendor"})
    assert not result.errors
    assert result.warnings
    assert "some_unknown_vendor" in result.warnings[0]
