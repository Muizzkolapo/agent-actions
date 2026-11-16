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


def _anthropic_errors(vendor_params: dict, **settings) -> list[str]:
    config = {"model_vendor": "anthropic", "model_name": "m", "vendor_params": vendor_params}
    config.update({"temperature": None, "top_p": None, "max_tokens": None, **settings})
    result = WorkflowResolutionService(action_configs={"write_quiz": config}).resolve_all()
    return [e.message for e in result.errors if e.location.config_field == "vendor_params"]


THINKING = {"thinking": {"type": "enabled", "budget_tokens": 2048}}


class TestAnthropicThinkingConflicts:
    """With thinking on, the API takes temperature 1, top_p >= 0.95, no top_k, no forced tool."""

    def test_thinking_with_the_defaults_passes(self):
        assert _anthropic_errors(THINKING) == []

    def test_a_temperature_other_than_1_is_refused(self):
        (message,) = _anthropic_errors(THINKING, temperature=0.2)

        assert message == (
            "Action 'write_quiz': vendor_params for 'anthropic': with thinking on, "
            "temperature must be 1 or unset, not 0.2."
        )

    def test_temperature_1_passes(self):
        assert _anthropic_errors(THINKING, temperature=1.0) == []

    def test_a_temperature_in_extra_body_is_read_too(self):
        (message,) = _anthropic_errors({**THINKING, "extra_body": {"temperature": 0}})

        assert "temperature must be 1 or unset, not 0" in message

    def test_a_low_top_p_is_refused_and_095_passes(self):
        (message,) = _anthropic_errors(THINKING, top_p=0.9)

        assert "top_p must be 0.95 or more, or unset, not 0.9" in message
        assert _anthropic_errors(THINKING, top_p=0.95) == []

    def test_top_k_is_refused(self):
        (message,) = _anthropic_errors({**THINKING, "extra_body": {"top_k": 40}})

        assert "top_k must be unset, not 40" in message

    def test_a_forced_tool_is_refused(self):
        (message,) = _anthropic_errors({**THINKING, "tool_choice": {"type": "tool", "name": "q"}})

        assert "tool_choice cannot force a tool (type 'tool')" in message

    def test_a_budget_at_the_default_max_tokens_is_refused(self):
        (message,) = _anthropic_errors({"thinking": {"type": "enabled", "budget_tokens": 4096}})

        assert message.endswith(
            "thinking.budget_tokens (4096) must be below max_tokens (4096, the default)."
        )

    def test_a_budget_below_the_actions_max_tokens_passes(self):
        thinking = {"thinking": {"type": "enabled", "budget_tokens": 8000}}

        assert _anthropic_errors(thinking, max_tokens=16000) == []
        assert _anthropic_errors(thinking, max_tokens=8000) != []

    def test_the_interleaved_thinking_beta_lets_the_budget_run_past(self):
        params = {
            "thinking": {"type": "enabled", "budget_tokens": 8000},
            "extra_headers": {"anthropic-beta": "interleaved-thinking-2025-05-14"},
        }

        assert _anthropic_errors(params) == []

    def test_disabled_thinking_checks_nothing(self):
        params = {"thinking": {"type": "disabled"}, "extra_body": {"top_k": 40}}

        assert _anthropic_errors(params, temperature=0.2) == []

    def test_adaptive_thinking_checks_sampling_but_has_no_budget(self):
        (message,) = _anthropic_errors({"thinking": {"type": "adaptive"}}, temperature=0.5)

        assert "temperature must be 1 or unset" in message
