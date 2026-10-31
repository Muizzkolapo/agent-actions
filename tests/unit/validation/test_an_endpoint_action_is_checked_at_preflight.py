"""Preflight holds an action on a declared endpoint to the endpoint rules.

An endpoint runs with structured output only, so the action needs json_mode and a
schema. Its url, credential and header variables must be set, and a command auth
must be on PATH. The generic api_key check does not apply: the credential comes
from the endpoint, not from the action. Every text names the action and the
endpoint, and the environment checks are reported once per endpoint.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.llm.config.endpoints import load_project_endpoints
from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService

ENDPOINTS = {
    "lab-vllm": {"url": "${LAB_VLLM_URL}", "auth": "none"},
    "azure-gpt": {
        "url": "https://r.openai.azure.com/openai/v1",
        "auth": {"env": "AZURE_OPENAI_KEY", "header": "api-key"},
        "headers": {"X-Trace": "${TRACE_TOKEN}"},
    },
    "vertex-gemini": {
        "url": "https://aiplatform.googleapis.com/v1/projects/p/locations/global/endpoints/openapi",
        "auth": {"command": ["agac-no-such-command-631", "token"]},
    },
}

SCHEMA = {"name": "classify", "fields": [{"id": "label", "type": "string"}]}


def _action(vendor: str, **overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "kind": "llm",
        "model_vendor": vendor,
        "model_name": "m",
        "json_mode": True,
        "schema": SCHEMA,
        "api_key": "OLLAMA_API_KEY",
    }
    config.update(overrides)
    return config


def _errors(actions: dict[str, dict[str, Any]]) -> list[str]:
    result = WorkflowResolutionService(action_configs=actions).resolve_all()
    return [e.message for e in result.errors]


@pytest.fixture(autouse=True)
def _endpoints(monkeypatch):
    load_project_endpoints({"endpoints": ENDPOINTS})
    monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)
    monkeypatch.setenv("LAB_VLLM_URL", "http://gpu-box:8000/v1")
    monkeypatch.setenv("AZURE_OPENAI_KEY", "azure-secret-value")
    monkeypatch.setenv("TRACE_TOKEN", "trace-value")
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)


def test_an_endpoint_action_with_a_schema_and_its_variables_set_passes():
    errors = _errors({"classify": _action("lab-vllm"), "review": _action("azure-gpt")})

    assert errors == []


def test_the_generic_api_key_check_does_not_apply_to_an_endpoint_action():
    # OLLAMA_API_KEY is unset: an openai action is refused for it, an endpoint action is not.
    errors = _errors({"classify": _action("lab-vllm"), "cloud": _action("openai")})

    assert [e for e in errors if "OLLAMA_API_KEY" in e] == [
        "API key environment variable 'OLLAMA_API_KEY' is not set "
        "(required by action 'cloud', vendor 'openai')"
    ]


def test_json_mode_false_is_refused_with_the_structured_output_text():
    errors = _errors({"summarise": _action("lab-vllm", json_mode=False)})

    assert errors == [
        "Action 'summarise': endpoint 'lab-vllm' runs with structured output only; "
        "set json_mode: true and add a schema"
    ]


def test_json_mode_false_on_a_built_in_vendor_is_not_an_endpoint_refusal():
    errors = _errors({"summarise": _action("openai", json_mode=False)})

    assert [e for e in errors if "structured output" in e] == []


@pytest.mark.parametrize("missing", [{"schema": None}, {"schema": {}}], ids=["none", "empty"])
def test_an_endpoint_action_without_a_schema_is_refused(missing):
    errors = _errors({"classify": _action("lab-vllm", **missing)})

    assert errors == [
        "Action 'classify': endpoint 'lab-vllm' runs with structured output only; "
        "add a schema to this action"
    ]


def test_a_schema_named_by_file_counts_as_a_schema():
    config = _action("lab-vllm", schema=None, schema_name="classify")

    assert _errors({"classify": config}) == []


def test_an_unset_url_variable_is_refused(monkeypatch):
    monkeypatch.delenv("LAB_VLLM_URL")

    assert _errors({"classify": _action("lab-vllm")}) == [
        "Action 'classify': endpoint 'lab-vllm' reads its url from LAB_VLLM_URL, which is not set"
    ]


def test_an_unset_credential_variable_is_refused(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_KEY", "")

    assert _errors({"review": _action("azure-gpt")}) == [
        "Action 'review': endpoint 'azure-gpt' reads AZURE_OPENAI_KEY, which is not set"
    ]


def test_an_unset_header_variable_is_refused(monkeypatch):
    monkeypatch.delenv("TRACE_TOKEN")

    assert _errors({"review": _action("azure-gpt")}) == [
        "Action 'review': endpoint 'azure-gpt' reads TRACE_TOKEN for header X-Trace, "
        "which is not set"
    ]


def test_a_command_that_is_not_on_path_is_refused():
    assert _errors({"classify": _action("vertex-gemini")}) == [
        "Action 'classify': endpoint 'vertex-gemini' auth command "
        "'agac-no-such-command-631' is not on PATH"
    ]


def test_a_command_that_is_on_path_passes():
    load_project_endpoints(
        {"endpoints": {"local": {"url": "http://h/v1", "auth": {"command": ["python3"]}}}}
    )

    assert _errors({"classify": _action("local")}) == []


def test_an_environment_refusal_is_reported_once_per_endpoint(monkeypatch):
    monkeypatch.delenv("LAB_VLLM_URL")
    actions = {"first": _action("lab-vllm"), "second": _action("lab-vllm")}

    assert _errors(actions) == [
        "Action 'first': endpoint 'lab-vllm' reads its url from LAB_VLLM_URL, which is not set"
    ]


def test_the_schema_rule_is_reported_for_every_action(monkeypatch):
    actions = {
        "first": _action("lab-vllm", schema=None),
        "second": _action("lab-vllm", schema=None),
    }

    assert [e.split(":")[0] for e in _errors(actions)] == ["Action 'first'", "Action 'second'"]


def test_skipping_env_validation_keeps_the_schema_rules(monkeypatch):
    monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")
    monkeypatch.delenv("LAB_VLLM_URL")
    errors = _errors({"classify": _action("lab-vllm", json_mode=False)})

    assert errors == [
        "Action 'classify': endpoint 'lab-vllm' runs with structured output only; "
        "set json_mode: true and add a schema"
    ]


def test_every_endpoint_refusal_points_at_the_action_and_names_the_field(monkeypatch):
    monkeypatch.delenv("LAB_VLLM_URL")
    result = WorkflowResolutionService(
        action_configs={"classify": _action("lab-vllm", json_mode=False)}
    ).resolve_all()

    fields = {(e.location.agent_name, e.location.config_field) for e in result.errors}
    assert fields == {("classify", "json_mode"), ("classify", "model_vendor")}
