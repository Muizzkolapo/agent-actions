"""A vendor that takes no key is not asked for one; a vendor that takes one is told its own.

Expansion and preflight decide "this action needs an api_key" from one rule. The mock
(`agac-provider`), a local Ollama daemon and a llamafile server send no key, so an action
on one of them expands and inspects with no `api_key` at any level. A vendor that sends a
key is still refused without one, and the fix text names that vendor's variable.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.logging.errors import format_user_error
from agent_actions.output.response.expander_validation import validate_required_fields
from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService
from tests._support.agac_cli import run_agac

FIXTURE = Path(__file__).resolve().parents[2] / "integration" / "fixtures" / "expectation_authors"

KEYLESS = ["agac-provider", "ollama_local", "llamafile"]
KEYED = ["openai", "anthropic", "ollama_cloud"]


def _refusal(vendor: str) -> ConfigValidationError:
    with pytest.raises(ConfigValidationError) as info:
        validate_required_fields({"model_vendor": vendor, "model_name": "m"}, "classify")
    return info.value


class TestExpansion:
    @pytest.mark.parametrize("vendor", KEYLESS)
    def test_a_vendor_that_takes_no_key_expands_without_one(self, vendor):
        validate_required_fields({"model_vendor": vendor, "model_name": "m"}, "classify")

    @pytest.mark.parametrize("vendor", KEYED)
    def test_a_vendor_that_takes_a_key_is_refused_without_one(self, vendor):
        assert _refusal(vendor).context["missing_fields"] == ["api_key"]

    def test_a_keyless_vendor_still_needs_a_model_name(self):
        with pytest.raises(ConfigValidationError) as info:
            validate_required_fields({"model_vendor": "agac-provider"}, "classify")

        assert info.value.context["missing_fields"] == ["model_name"]


class TestTheFixText:
    @pytest.mark.parametrize(
        ("vendor", "variable"),
        [
            ("openai", "OPENAI_API_KEY"),
            ("anthropic", "ANTHROPIC_API_KEY"),
            ("ollama_cloud", "OLLAMA_API_KEY"),
        ],
    )
    def test_it_names_the_vendors_own_variable_at_every_level(self, vendor, variable):
        text = format_user_error(_refusal(vendor))

        assert text.count(f"api_key: ${{{variable}}}") == 3
        assert text.count("api_key:") == 3

    def test_an_openai_action_is_not_told_to_set_the_anthropic_variable(self):
        text = format_user_error(_refusal("openai"))

        assert "ANTHROPIC_API_KEY" not in text

    def test_with_no_vendor_it_names_no_vendors_variable(self):
        with pytest.raises(ConfigValidationError) as info:
            validate_required_fields({"model_name": "m"}, "classify")

        text = format_user_error(info.value)

        assert text.count("api_key: ${YOUR_PROVIDER_API_KEY}") == 3
        assert "ANTHROPIC_API_KEY" not in text


class TestPreflight:
    @pytest.mark.parametrize("vendor", [*KEYLESS, "tool", "hitl"])
    def test_a_vendor_that_takes_no_key_is_not_checked_for_one(self, monkeypatch, vendor):
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)

        svc = WorkflowResolutionService(action_configs={"a": {"model_vendor": vendor}})

        assert svc._check_api_keys()[0] == []

    @pytest.mark.parametrize(
        ("vendor", "variable"),
        [("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY")],
    )
    def test_a_vendor_that_takes_a_key_is_checked_for_its_own(self, monkeypatch, vendor, variable):
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)
        monkeypatch.delenv(variable, raising=False)

        svc = WorkflowResolutionService(action_configs={"a": {"model_vendor": vendor}})

        assert [e.location.raw_reference for e in svc._check_api_keys()[0]] == [variable]


def _project(tmp_path: Path, vendor: str) -> Path:
    """The fixture project with *vendor* as the workflow's vendor and no api_key anywhere."""
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    project = root / "agent_actions.yml"
    project.write_text(
        "".join(line for line in project.read_text().splitlines(True) if "api_key" not in line)
    )
    workflow = root / "agent_workflow" / "repair_auto" / "agent_config" / "repair_auto.yml"
    text = workflow.read_text().replace("  api_key: OLLAMA_API_KEY\n", "")
    workflow.write_text(text.replace("model_vendor: ollama_cloud", f"model_vendor: {vendor}"))
    assert "api_key" not in project.read_text() + workflow.read_text()
    return root


NO_KEYS = {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "", "OLLAMA_API_KEY": ""}


class TestInspect:
    def test_a_workflow_on_the_mock_inspects_with_no_key_at_any_level(self, tmp_path):
        result = run_agac(_project(tmp_path, "agac-provider"), "inspect", "-a", "repair_auto")

        assert "missing required configuration" not in result.stdout + result.stderr
        assert result.returncode == 0, result.stdout + result.stderr

    def test_a_workflow_on_openai_is_refused_and_told_its_own_variable(self, tmp_path):
        result = run_agac(_project(tmp_path, "openai"), "inspect", "-a", "repair_auto", env=NO_KEYS)
        output = result.stdout + result.stderr

        assert result.returncode != 0
        assert "is missing required configuration: 'api_key'" in output
        assert "api_key: ${OPENAI_API_KEY}" in output
        assert "ANTHROPIC_API_KEY" not in output
