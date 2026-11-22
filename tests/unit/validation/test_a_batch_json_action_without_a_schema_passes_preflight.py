"""A batch action in JSON mode with no schema passes preflight, as the same action online does.

Online runs such an action, asking the vendor for JSON with no schema. Preflight refused it in
batch ("Schema is required for batch processing when json_mode is enabled"), so a workflow that
ran online stopped when its `run_mode` was set to `batch`.
"""

from __future__ import annotations

import pytest

from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService

BATCH_VENDORS = ["openai", "groq", "anthropic", "gemini", "ollama_local", "agac-provider"]


@pytest.fixture(autouse=True)
def _skip_key_presence_checks(monkeypatch):
    monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")


def _errors(vendor: str = "openai", **config) -> list:
    configs = {"write_quiz": {"model_vendor": vendor, "model_name": "m", **config}}
    return WorkflowResolutionService(action_configs=configs).resolve_all().errors


@pytest.mark.parametrize("vendor", BATCH_VENDORS)
def test_a_batch_json_action_without_a_schema_passes(vendor):
    assert _errors(vendor, run_mode="batch") == []


def test_json_mode_set_explicitly_passes_too():
    assert _errors(run_mode="batch", json_mode=True) == []


def test_it_passes_as_the_same_action_online_does():
    assert _errors(run_mode="batch") == _errors(run_mode="online") == []


@pytest.mark.parametrize(
    "config",
    [
        {"schema": "quiz"},
        {"schema": {"type": "object", "properties": {"q": {"type": "string"}}}},
        {"schema_name": "quiz"},
        {"json_mode": False},
        {"kind": "tool"},
    ],
    ids=["schema", "inline-schema", "schema_name", "text-mode", "tool"],
)
def test_a_batch_action_with_a_schema_or_in_text_mode_still_passes(config):
    assert _errors(run_mode="batch", **config) == []
