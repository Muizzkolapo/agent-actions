"""base_url on a vendor whose client does not send to it is refused at preflight.

The anthropic, gemini, groq and cohere clients always call their vendor's
default endpoint. A base_url on those actions was accepted and ignored, so a
request meant for a local server went to the cloud vendor.
"""

from __future__ import annotations

import pytest

from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService

LOCAL = "http://localhost:8080/v1"
HINT = "Remove base_url, or set model_vendor: openai for an OpenAI-compatible server."


@pytest.fixture(autouse=True)
def _skip_key_presence_checks(monkeypatch):
    monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")


def _base_url_errors(action_configs: dict) -> list:
    result = WorkflowResolutionService(action_configs=action_configs).resolve_all()
    return [e for e in result.errors if e.location.config_field == "base_url"]


def _action(vendor: str, base_url: str | None = LOCAL) -> dict:
    return {"model_vendor": vendor, "model_name": "m", "base_url": base_url}


@pytest.mark.parametrize("vendor", ["anthropic", "gemini", "groq", "cohere"])
def test_base_url_is_refused_for_a_vendor_that_ignores_it(vendor):
    errors = _base_url_errors({"classify_local": _action(vendor)})

    assert [e.message for e in errors] == [
        f"Action 'classify_local': vendor '{vendor}' does not send requests to base_url."
    ]
    assert errors[0].hint == HINT
    assert errors[0].location.agent_name == "classify_local"
    assert errors[0].location.raw_reference == f"base_url={LOCAL}"


@pytest.mark.parametrize("vendor", ["openai", "ollama_local", "ollama_cloud"])
def test_base_url_is_allowed_for_a_vendor_that_sends_to_it(vendor):
    assert _base_url_errors({"classify_local": _action(vendor)}) == []


@pytest.mark.parametrize("vendor", ["tool", "hitl", "agac-provider"])
def test_base_url_inherited_by_an_action_that_sends_no_request_is_allowed(vendor):
    assert _base_url_errors({"step": _action(vendor)}) == []


@pytest.mark.parametrize("base_url", [None, ""])
def test_unset_base_url_is_not_refused(base_url):
    assert _base_url_errors({"summarize": _action("anthropic", base_url)}) == []


def test_only_the_ignoring_action_is_named_in_a_mixed_workflow():
    errors = _base_url_errors(
        {
            "classify_local": _action("openai"),
            "summarize": _action("anthropic"),
            "tidy": _action("tool"),
        }
    )

    assert [e.location.agent_name for e in errors] == ["summarize"]


def test_refusal_comes_before_any_key_probe(monkeypatch):
    monkeypatch.delenv("AA_SKIP_ENV_VALIDATION")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-1234567890")
    probed: list = []
    monkeypatch.setattr(
        "agent_actions.validation.preflight.key_verifier.verify_keys",
        lambda targets, **_: probed.extend(targets) or [],
    )
    config = {**_action("anthropic"), "api_key": "ANTHROPIC_API_KEY"}

    result = WorkflowResolutionService(
        action_configs={"summarize": config}, verify_keys=True
    ).resolve_all()

    assert [e.location.config_field for e in result.errors] == ["base_url"]
    assert probed == []
