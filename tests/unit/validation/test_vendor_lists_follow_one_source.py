"""Every vendor list and batch rule reads one source, so a runtime profile vendor appears in each."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_actions.llm.config.runtime_profiles import RUNTIME_PROFILES
from agent_actions.llm.config.vendor import VendorType
from agent_actions.output.response.config_schema import AgentConfig
from agent_actions.tooling.docs.scanner.component_scanners import scan_vendors
from agent_actions.validation.action_validators.vendor_compatibility_validator import (
    VendorCompatibilityValidator,
)
from agent_actions.validation.orchestration.action_entry_validation_orchestrator import (
    ActionEntryValidationContext,
)
from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService

ALL_VENDORS = [v.value for v in VendorType] + list(RUNTIME_PROFILES)
BATCH_REFUSAL = "does not support run_mode: batch. Set run_mode: online."


def _entry_result(vendor: str, run_mode: str = "batch"):
    context = ActionEntryValidationContext(
        entry={"run_mode": run_mode, "model_vendor": vendor},
        agent_name_context="classify_local",
    )
    return VendorCompatibilityValidator().validate(context)


class TestVendorLists:
    def test_the_docs_vendor_scan_lists_every_vendor(self, tmp_path: Path):
        scanned = scan_vendors(tmp_path)

        assert sorted(scanned) == sorted(ALL_VENDORS)

    def test_the_docs_vendor_scan_gives_llamafile_its_default_url(self, tmp_path: Path):
        llamafile = scan_vendors(tmp_path)["llamafile"]

        assert "http://localhost:8080/v1" in llamafile["docstring"]

    @pytest.mark.parametrize("vendor", ALL_VENDORS)
    def test_the_model_vendor_help_text_names_every_vendor(self, vendor: str):
        description = AgentConfig.model_fields["model_vendor"].description

        assert f"'{vendor}'" in description


class TestEntryValidatorBatch:
    @pytest.mark.parametrize("vendor", ["llamafile", "cohere"])
    def test_batch_on_a_vendor_that_cannot_batch_is_refused(self, vendor: str):
        result = _entry_result(vendor)

        assert [e for e in result.errors if BATCH_REFUSAL in e] == [
            f"{_entry_description()}: vendor '{vendor}' {BATCH_REFUSAL}"
        ]

    @pytest.mark.parametrize("vendor", ["openai", "anthropic", "gemini", "groq", "ollama_local"])
    def test_batch_on_a_vendor_that_can_batch_passes(self, vendor: str):
        result = _entry_result(vendor)

        assert result.errors == []
        assert result.warnings == []

    def test_online_on_llamafile_passes(self):
        result = _entry_result("llamafile", run_mode="online")

        assert result.errors == []

    def test_an_unknown_vendor_still_only_warns(self):
        result = _entry_result("some_unknown_vendor")

        assert result.errors == []
        assert any("some_unknown_vendor" in w for w in result.warnings)

    def test_the_tool_vendor_refusal_lists_only_vendors_that_can_batch(self):
        result = _entry_result("tool")

        listed = result.errors[0].split("Use one of: ")[1].split(" for batch mode")[0]
        assert listed.split(", ") == [
            "anthropic",
            "gemini",
            "groq",
            "ollama_cloud",
            "ollama_local",
            "openai",
        ]


def _entry_description() -> str:
    context = ActionEntryValidationContext(
        entry={"run_mode": "batch", "model_vendor": "llamafile"},
        agent_name_context="classify_local",
    )
    return context.description


class TestOneRule:
    def test_preflight_and_the_entry_validator_refuse_llamafile_batch_with_one_text(
        self, monkeypatch
    ):
        monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")
        preflight = WorkflowResolutionService(
            action_configs={
                "classify_local": {
                    "kind": "llm",
                    "model_vendor": "llamafile",
                    "model_name": "local",
                    "run_mode": "batch",
                    "json_mode": False,
                }
            }
        ).resolve_all()
        refusal = next(e for e in preflight.errors if "batch" in e.message)

        entry_error = _entry_result("llamafile").errors[0]

        preflight_text = f"{refusal.message} {refusal.hint}"
        assert preflight_text.endswith(BATCH_REFUSAL)
        assert entry_error.endswith(BATCH_REFUSAL)
