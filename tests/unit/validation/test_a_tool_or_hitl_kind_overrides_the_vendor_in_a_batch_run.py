"""A tool or hitl kind runs online even when its model_vendor cannot batch."""

from __future__ import annotations

import pytest

from agent_actions.validation.action_validators.vendor_compatibility_validator import (
    VendorCompatibilityValidator,
)
from agent_actions.validation.orchestration.action_entry_validation_orchestrator import (
    ActionEntryValidationContext,
)


@pytest.mark.parametrize(
    "entry",
    [
        {"kind": "tool", "model_vendor": "llamafile"},
        {"kind": "hitl", "model_vendor": "some_unknown_vendor"},
    ],
    ids=["tool-over-llamafile", "hitl-over-unknown"],
)
def test_the_entry_check_neither_refuses_nor_warns(entry):
    context = ActionEntryValidationContext(
        entry={"run_mode": "batch", **entry}, agent_name_context="review_step"
    )

    result = VendorCompatibilityValidator().validate(context)

    assert (result.errors, result.warnings) == ([], [])


@pytest.mark.parametrize("vendor", ["llamafile", "some_unknown_vendor"])
def test_the_same_vendor_under_an_llm_kind_still_gets_its_message(vendor):
    context = ActionEntryValidationContext(
        entry={"run_mode": "batch", "kind": "llm", "model_vendor": vendor},
        agent_name_context="review_step",
    )

    result = VendorCompatibilityValidator().validate(context)

    assert result.errors + result.warnings != []
