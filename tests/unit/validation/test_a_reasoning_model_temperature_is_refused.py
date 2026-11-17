"""A temperature other than 1 on an OpenAI reasoning model is refused at preflight.

OpenAI refuses it on every record of an o-series or gpt-5 model. The batch client
dropped it for three exact model names and sent it for every other one, so the same
action ran with another temperature than it asked for, or failed every record.
gpt-5.1 and later reason only when a reasoning_effort other than none is set.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService


@pytest.fixture(autouse=True)
def _skip_key_presence_checks(monkeypatch):
    monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")


def _temperature_errors(**config: Any) -> list:
    action = {"model_vendor": "openai", "model_name": "o3-mini", "temperature": 0.2, **config}
    result = WorkflowResolutionService(action_configs={"classify": action}).resolve_all()
    return [e for e in result.errors if e.location.config_field == "temperature"]


@pytest.mark.parametrize(
    "model",
    ["o1", "o3-mini", "o4-mini-2025-04-16", "gpt-5", "gpt-5-nano", "gpt-5-2025-08-07"],
)
def test_a_reasoning_model_refuses_a_temperature_other_than_1(model):
    errors = _temperature_errors(model_name=model)

    assert [e.message for e in errors] == [
        f"Action 'classify': model '{model}' is a reasoning model "
        "and takes only the default temperature (1), not 0.2."
    ]
    assert errors[0].hint == (
        "Set temperature: 1 on this action, or use a model that does not reason."
    )


def test_gpt_5_1_is_refused_once_it_is_told_to_reason():
    assert _temperature_errors(model_name="gpt-5.1", vendor_params={"reasoning_effort": "low"})


@pytest.mark.parametrize(
    "config",
    [
        {"temperature": 1},
        {"temperature": None},
        {"model_name": "gpt-4o-mini"},
        {"model_name": "gpt-5-chat-latest"},
        {"model_name": "gpt-5.1"},
        {"model_name": "gpt-5.1", "vendor_params": {"reasoning_effort": "none"}},
        {"base_url": "http://localhost:8080/v1"},
        {"model_vendor": "groq"},
    ],
)
def test_anything_else_passes(config):
    assert _temperature_errors(**config) == []
