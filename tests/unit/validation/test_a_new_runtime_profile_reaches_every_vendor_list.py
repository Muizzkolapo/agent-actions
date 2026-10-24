"""A runtime profile added to the table reaches every vendor list and both batch checks.

The profile below exists only in this test, so a list that names today's vendors by
hand cannot pass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest

from agent_actions.llm.config import runtime_profiles
from agent_actions.llm.config.vendor import vendor_names
from agent_actions.llm.realtime.services import invocation
from agent_actions.tooling.docs.scanner.component_scanners import scan_vendors
from agent_actions.validation.action_validators.vendor_compatibility_validator import (
    VendorCompatibilityValidator,
)
from agent_actions.validation.orchestration.action_entry_validation_orchestrator import (
    ActionEntryValidationContext,
)
from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService

PROFILE_VENDOR = "probe_runtime_x"
BATCH_REFUSAL = "does not support run_mode: batch. Set run_mode: online."


class _ProbeRuntimeClient:
    CAPABILITIES: ClassVar[dict[str, Any]] = {"supports_batch": False}


@pytest.fixture(autouse=True)
def _probe_profile(monkeypatch):
    profile = runtime_profiles.RuntimeProfile(
        wire="openai_chat",
        default_base_url="http://localhost:9911/v1",
        api_key_required=False,
        supports_batch=False,
        supports_tools=False,
        enforces_json_schema=True,
        enforces_json_object=False,
        verified_with="probe 0.0.1",
    )
    monkeypatch.setitem(runtime_profiles.RUNTIME_PROFILES, PROFILE_VENDOR, profile)
    monkeypatch.setitem(invocation.CLIENT_REGISTRY, PROFILE_VENDOR, _ProbeRuntimeClient)
    monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")


def test_vendor_names_includes_the_new_profile():
    assert PROFILE_VENDOR in vendor_names()


def test_the_docs_vendor_scan_lists_the_new_profile_with_its_url(tmp_path: Path):
    entry = scan_vendors(tmp_path)[PROFILE_VENDOR]

    assert "http://localhost:9911/v1" in entry["docstring"]


def test_both_batch_checks_refuse_the_new_profile_with_one_text():
    context = ActionEntryValidationContext(
        entry={"run_mode": "batch", "model_vendor": PROFILE_VENDOR},
        agent_name_context="classify_local",
    )
    entry_errors = VendorCompatibilityValidator().validate(context).errors

    preflight = WorkflowResolutionService(
        action_configs={
            "classify_local": {
                "kind": "llm",
                "model_vendor": PROFILE_VENDOR,
                "model_name": "local",
                "run_mode": "batch",
                "json_mode": False,
            }
        }
    ).resolve_all()
    refusals = [f"{e.message} {e.hint}" for e in preflight.errors if "batch" in e.message]

    assert entry_errors == [f"{context.description}: vendor '{PROFILE_VENDOR}' {BATCH_REFUSAL}"]
    assert refusals == [f"Action 'classify_local': vendor '{PROFILE_VENDOR}' {BATCH_REFUSAL}"]


@pytest.mark.parametrize("vendor", ["hitl", "agac-provider"])
def test_a_vendor_that_runs_no_model_still_gets_the_batch_warning(vendor: str):
    context = ActionEntryValidationContext(
        entry={"run_mode": "batch", "model_vendor": vendor},
        agent_name_context="classify_local",
    )
    result = VendorCompatibilityValidator().validate(context)

    assert result.errors == []
    assert [w for w in result.warnings if f"'{vendor}' may not support" in w] != []
