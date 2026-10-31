"""`--verify-keys` sends one structured-output request to each declared endpoint.

A server cannot say whether it honours `json_schema`; one small request proves it. A
refused credential and a reply that does not match the probe's schema are errors with
the endpoint named. The probe costs one model call per endpoint, so it runs only under
`--verify-keys`, once per endpoint, and not when preflight already found an error.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from agent_actions.llm.config.endpoints import load_project_endpoints
from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService
from tests._support.fake_endpoint import FakeEndpoint

SECRET = "probe-secret-value-abcdef123456"
NOT_HONOURED = (
    "endpoint 'lab' does not honour response_format json_schema; "
    "agac supports only endpoints with OpenAI structured output"
)
SCHEMA = {"name": "classify", "fields": [{"id": "label", "type": "string"}]}


@pytest.fixture
def probe():
    return importlib.import_module("agent_actions.llm.providers.openai.endpoint_probe")


def _declare(url: str, **auth: Any) -> None:
    load_project_endpoints({"endpoints": {"lab": {"url": url, "auth": auth or "none"}}})


def _action(vendor: str = "lab", **overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "kind": "llm",
        "model_vendor": vendor,
        "model_name": "stub-7b",
        "json_mode": True,
        "schema": SCHEMA,
    }
    config.update(overrides)
    return config


class TestTheProbe:
    def test_an_endpoint_that_honours_the_schema_passes(self, probe):
        with FakeEndpoint() as server:
            _declare(server.base_url)

            result = probe.probe_endpoint("lab", "stub-7b")

        assert result.ok and result.error is None
        (request,) = server.requests
        assert request["body"]["model"] == "stub-7b"
        assert request["body"]["max_tokens"] == 16
        sent = request["body"]["response_format"]
        assert sent["type"] == "json_schema"
        assert sent["json_schema"]["name"] == "agac_probe"
        assert set(sent["json_schema"]["schema"]["properties"]) == {"ok"}

    @pytest.mark.parametrize("mode", ["ignore", "prose"])
    def test_an_endpoint_that_ignores_the_schema_is_refused_by_name(self, probe, mode):
        with FakeEndpoint(mode=mode) as server:
            _declare(server.base_url)

            result = probe.probe_endpoint("lab", "stub-7b")

        assert not result.ok
        assert result.error == NOT_HONOURED

    def test_a_reply_with_an_extra_field_does_not_count_as_honoured(self, probe):
        with FakeEndpoint() as server:
            server.content = '{"ok": true, "extra": 1}'
            _declare(server.base_url)

            result = probe.probe_endpoint("lab", "stub-7b")

        assert result.error == NOT_HONOURED

    @pytest.mark.parametrize("status", [401, 403])
    def test_a_refused_credential_is_an_error_with_the_status(self, probe, status, monkeypatch):
        monkeypatch.setenv("LAB_KEY", SECRET)
        with FakeEndpoint(statuses=[status]) as server:
            _declare(server.base_url, env="LAB_KEY", header="X-Api-Key")

            result = probe.probe_endpoint("lab", "stub-7b")

        assert result.error == f"endpoint 'lab' refused the credential (HTTP {status})"
        assert server.requests[0]["headers"]["x-api-key"] == SECRET

    def test_a_server_that_cannot_be_reached_is_an_error_naming_the_endpoint(self, probe):
        _declare("http://127.0.0.1:1/v1")

        result = probe.probe_endpoint("lab", "stub-7b")

        assert not result.ok
        assert result.error.startswith("endpoint 'lab' could not be reached: ")


class TestPreflightWiring:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)

    def test_verify_keys_probes_each_endpoint_once_and_reports_a_refusal(self):
        with FakeEndpoint(mode="ignore") as server:
            _declare(server.base_url)
            actions = {"first": _action(), "second": _action()}

            result = WorkflowResolutionService(
                action_configs=actions, verify_keys=True
            ).resolve_all()

        assert [e.message for e in result.errors] == [NOT_HONOURED]
        assert result.errors[0].location.agent_name == "(workflow)"
        assert len(server.requests) == 1
        assert server.requests[0]["body"]["model"] == "stub-7b"

    def test_an_endpoint_that_honours_the_schema_adds_no_error(self):
        with FakeEndpoint() as server:
            _declare(server.base_url)

            result = WorkflowResolutionService(
                action_configs={"classify": _action()}, verify_keys=True
            ).resolve_all()

        assert result.errors == []
        assert len(server.requests) == 1

    def test_without_verify_keys_no_request_is_sent(self):
        with FakeEndpoint(mode="ignore") as server:
            _declare(server.base_url)

            result = WorkflowResolutionService(action_configs={"classify": _action()}).resolve_all()

        assert result.errors == []
        assert server.requests == []

    def test_an_earlier_error_stops_the_probe(self):
        with FakeEndpoint() as server:
            _declare(server.base_url)
            actions = {"classify": _action(json_mode=False)}

            result = WorkflowResolutionService(
                action_configs=actions, verify_keys=True
            ).resolve_all()

        assert any("structured output only" in e.message for e in result.errors)
        assert server.requests == []

    def test_skipping_env_validation_skips_the_probe_too(self, monkeypatch):
        monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")
        with FakeEndpoint(mode="ignore") as server:
            _declare(server.base_url)

            result = WorkflowResolutionService(
                action_configs={"classify": _action()}, verify_keys=True
            ).resolve_all()

        assert result.errors == []
        assert server.requests == []

    def test_a_built_in_vendor_beside_an_endpoint_is_not_probed_as_an_endpoint(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-000000000000000000000")
        with FakeEndpoint() as server:
            _declare(server.base_url)
            actions = {
                "classify": _action(),
                "cloud": _action("openai", api_key="OPENAI_API_KEY", model_name="gpt-4o-mini"),
            }

            result = WorkflowResolutionService(
                action_configs=actions, verify_keys=False
            ).resolve_all()

        assert result.errors == []
        assert server.requests == []
