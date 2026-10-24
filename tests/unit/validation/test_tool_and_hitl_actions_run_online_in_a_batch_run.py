"""A tool or hitl action runs online inside a batch run, so no batch check stops it.

The pipeline runs these actions online whatever run_mode says, so a batch default
inherited from a workflow must neither refuse nor warn on them. Their clients have
no batch API, and say so.
"""

from __future__ import annotations

import pytest

from agent_actions.llm.providers.hitl.client import HitlClient
from agent_actions.llm.providers.tools.client import ToolClient
from agent_actions.validation.action_validators.vendor_compatibility_validator import (
    VendorCompatibilityValidator as EntryVendorCheck,
)
from agent_actions.validation.orchestration.action_entry_validation_orchestrator import (
    ActionEntryValidationContext,
)
from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService
from agent_actions.validation.preflight.vendor_compatibility_validator import (
    VendorCompatibilityValidator as PreflightVendorCheck,
)

BATCH_REFUSAL = "does not support run_mode: batch."


@pytest.mark.parametrize("client", [ToolClient, HitlClient])
def test_the_client_says_it_has_no_batch_api(client):
    assert client.CAPABILITIES["supports_batch"] is False


def _entry(**entry):
    context = ActionEntryValidationContext(
        entry={"run_mode": "batch", **entry}, agent_name_context="review_step"
    )
    return EntryVendorCheck().validate(context)


@pytest.mark.parametrize(
    "entry",
    [
        {"kind": "tool"},
        {"kind": "hitl"},
        {"model_vendor": "tool"},
        {"model_vendor": "hitl"},
        {"kind": "tool", "model_vendor": "openai"},
        {"kind": "hitl", "model_vendor": "hitl"},
    ],
    ids=["kind-tool", "kind-hitl", "vendor-tool", "vendor-hitl", "tool-over-openai", "hitl-both"],
)
def test_the_entry_check_neither_refuses_nor_warns(entry):
    result = _entry(**entry)

    assert (result.errors, result.warnings) == ([], [])


def test_the_entry_check_still_refuses_an_llm_vendor_that_cannot_batch():
    result = _entry(model_vendor="llamafile")

    assert [e for e in result.errors if BATCH_REFUSAL in e] != []


@pytest.fixture
def _no_key_checks(monkeypatch):
    monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")


@pytest.mark.usefixtures("_no_key_checks")
@pytest.mark.parametrize("vendor", ["tool", "hitl"])
def test_preflight_does_not_refuse_the_action(vendor):
    result = WorkflowResolutionService(
        action_configs={
            "review_step": {
                "kind": vendor,
                "model_vendor": vendor,
                "run_mode": "batch",
                "json_mode": False,
            },
            "classify_local": {
                "kind": "llm",
                "model_vendor": "llamafile",
                "model_name": "local",
                "run_mode": "batch",
                "json_mode": False,
            },
        }
    ).resolve_all()

    refused = sorted(e.location.agent_name for e in result.errors if BATCH_REFUSAL in e.message)
    assert refused == ["classify_local"]


@pytest.mark.parametrize("vendor", ["tool", "hitl"])
def test_the_preflight_feature_check_does_not_list_batch(vendor):
    check = PreflightVendorCheck()

    check.validate_vendor_config(
        {"model_vendor": vendor, "json_mode": False}, "review_step", "batch"
    )

    assert [e for e in check.get_errors() if "batch" in str(e)] == []
