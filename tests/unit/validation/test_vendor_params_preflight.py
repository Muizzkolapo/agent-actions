"""Preflight refuses a `vendor_params` key the vendor's request does not take, or agac sets.

Before, an unknown key in an action had no effect and drew no warning.
"""

from __future__ import annotations

import pytest

from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService


@pytest.fixture(autouse=True)
def _skip_key_presence_checks(monkeypatch):
    monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")


def _errors(vendor: str, vendor_params: dict) -> list:
    configs = {
        "write_quiz": {"model_vendor": vendor, "model_name": "m", "vendor_params": vendor_params}
    }
    result = WorkflowResolutionService(action_configs=configs).resolve_all()
    return [e for e in result.errors if e.location.config_field == "vendor_params"]


# One parameter each vendor's request takes that agac never sent before.
ACCEPTED = {
    "anthropic": {"thinking": {"type": "disabled"}, "tool_choice": {"type": "auto"}},
    "openai": {"reasoning_effort": "low", "seed": 7},
    "llamafile": {"seed": 7},
    "groq": {"reasoning_format": "parsed"},
    "gemini": {"thinking_config": {"thinking_budget": 0}, "safety_settings": []},
    "cohere": {"k": 5, "safety_mode": "OFF"},
    "ollama_local": {"think": True, "options": {"num_ctx": 8192}},
    "ollama_cloud": {"keep_alive": "5m"},
    "agac-provider": {"anything": 1},
}


@pytest.mark.parametrize("vendor", sorted(ACCEPTED))
def test_a_parameter_the_vendor_takes_passes(vendor):
    assert _errors(vendor, ACCEPTED[vendor]) == []


def test_an_unknown_key_is_refused_with_the_valid_keys():
    (error,) = _errors("anthropic", {"thinkng": {"type": "disabled"}})

    assert error.message.startswith(
        "Action 'write_quiz': vendor_params for 'anthropic': 'thinkng' is not a request "
        "parameter; valid keys: "
    )
    assert "thinking" in error.message
    assert "tool_choice" in error.message
    assert error.location.agent_name == "write_quiz"


@pytest.mark.parametrize("key", ["model", "messages", "tools", "system", "stream", "timeout"])
def test_a_key_agac_sets_is_refused(key):
    (error,) = _errors("anthropic", {key: "x"})

    assert error.message == (
        f"Action 'write_quiz': vendor_params for 'anthropic': '{key}' is set by agac and "
        "cannot be passed through."
    )


def test_a_reserved_key_is_not_offered_as_valid():
    (error,) = _errors("openai", {"nonesuch": 1})

    valid = error.message.split("valid keys: ", 1)[1]
    assert "model" not in valid.split(", ")
    assert "stream_options" not in valid.split(", ")


def test_gemini_keys_are_its_generation_config_fields():
    (error,) = _errors("gemini", {"reasoning_effort": "low"})

    assert "'reasoning_effort' is not a request parameter" in error.message
    assert "thinking_config" in error.message


def test_each_bad_key_is_named():
    errors = _errors("cohere", {"nope": 1, "model": "x", "k": 5})

    assert len(errors) == 2


@pytest.mark.parametrize("vendor", ["tool", "hitl"])
def test_an_action_that_sends_no_request_may_inherit_the_block(vendor):
    assert _errors(vendor, {"thinking": {"type": "disabled"}}) == []
