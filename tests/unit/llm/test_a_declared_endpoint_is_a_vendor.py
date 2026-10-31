"""A declared endpoint is a vendor: in every vendor list, with the OpenAI formats and client.

The endpoint client keeps the OpenAI client's requests and parsing; it adds the
endpoint's URL, headers, timeout and credential, fails a reply that does not match
the schema, and registers every secret it reads with the redactor.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.llm.config.endpoints import load_project_endpoints
from agent_actions.llm.config.runtime_profiles import wire_vendor
from agent_actions.llm.config.vendor import vendor_names
from agent_actions.llm.providers.client_base import get_or_create_client
from agent_actions.logging.filters import RedactingFilter, redact_text
from agent_actions.output.response.expander_validation import validate_required_fields
from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService
from agent_actions.validation.preflight.vendor_compatibility_validator import (
    _resolve_capabilities,
)
from tests._support.fake_endpoint import FakeEndpoint

SECRET = "endpoint-secret-value-abcdef123456"
SCHEMA = {
    "name": "classify",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"label": {"type": "string"}, "score": {"type": "integer"}},
        "required": ["label", "score"],
        "additionalProperties": False,
    },
}


@pytest.fixture
def compatible():
    return importlib.import_module("agent_actions.llm.providers.openai.compatible")


@pytest.fixture
def expander_validation():
    return importlib.import_module("agent_actions.output.response.expander_validation")


def _declare(url: str, **auth: Any) -> None:
    load_project_endpoints(
        {"endpoints": {"lab": {"url": url, "auth": auth or "none", "timeout_seconds": 5}}}
    )


class TestVendorLists:
    def test_a_declared_endpoint_is_in_the_vendor_names_and_speaks_openai(self):
        _declare("http://h/v1")

        assert "lab" in vendor_names()
        assert wire_vendor("lab") == "openai"
        assert wire_vendor("openai") == "openai"

    def test_an_undeclared_name_stays_unknown(self):
        assert "lab" not in vendor_names()
        assert wire_vendor("lab") == "lab"

    def test_an_endpoint_has_capabilities_that_refuse_batch(self):
        _declare("http://h/v1")

        capabilities = _resolve_capabilities("lab")
        assert capabilities is not None
        assert capabilities["supports_batch"] is False
        assert capabilities["supports_json_mode"] is True
        assert capabilities["required_fields"] == ["model_name"]
        assert "base_url" not in capabilities["optional_fields"]


class TestPreflightWiring:
    def test_an_inherited_base_url_on_an_endpoint_action_is_ignored(self, monkeypatch):
        monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")
        _declare("http://h/v1")
        config = {
            "model_vendor": "lab",
            "model_name": "m",
            "json_mode": True,
            "schema": SCHEMA,
            "base_url": "http://inherited/v1",
        }

        result = WorkflowResolutionService(action_configs={"classify": config}).resolve_all()

        assert result.errors == []

    def test_batch_on_an_endpoint_action_is_refused_with_the_existing_text(self, monkeypatch):
        monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")
        _declare("http://h/v1")
        config = {
            "model_vendor": "lab",
            "model_name": "m",
            "json_mode": True,
            "schema": SCHEMA,
            "run_mode": "batch",
        }

        result = WorkflowResolutionService(action_configs={"classify": config}).resolve_all()

        assert [f"{e.message} {e.hint}" for e in result.errors] == [
            "Action 'classify': vendor 'lab' does not support run_mode: batch. Set run_mode: online."
        ]


class TestExpanderRules:
    def test_an_endpoint_action_needs_no_api_key(self):
        _declare("http://h/v1")

        validate_required_fields({"model_vendor": "lab", "model_name": "m"}, "classify")

    def test_a_built_in_vendor_still_needs_an_api_key(self):
        with pytest.raises(ConfigValidationError) as info:
            validate_required_fields({"model_vendor": "openai", "model_name": "m"}, "classify")

        assert info.value.context["missing_fields"] == ["api_key"]

    @pytest.mark.parametrize(
        ("key", "text"),
        [
            (
                "api_key",
                "Action 'classify': endpoint 'lab' takes its credential from endpoints.lab.auth; "
                "remove api_key from the action",
            ),
            (
                "base_url",
                "Action 'classify': endpoint 'lab' takes its URL from endpoints.lab.url; "
                "remove base_url from the action",
            ),
        ],
    )
    def test_a_credential_or_url_written_on_the_action_is_refused(
        self, expander_validation, key, text
    ):
        _declare("http://h/v1")
        action = {"name": "classify", "model_vendor": "lab", key: "x"}
        agent = {"model_vendor": "lab", "model_name": "m", key: "x"}

        with pytest.raises(ConfigValidationError) as info:
            expander_validation.validate_endpoint_action(action, agent, "classify")

        assert info.value.context["reason"] == text

    def test_an_inherited_credential_is_not_refused(self, expander_validation):
        _declare("http://h/v1")
        action = {"name": "classify", "model_vendor": "lab"}
        agent = {"model_vendor": "lab", "model_name": "m", "api_key": "OPENAI_API_KEY"}

        expander_validation.validate_endpoint_action(action, agent, "classify")

    def test_a_built_in_vendor_action_may_set_both(self, expander_validation):
        action = {"name": "classify", "model_vendor": "openai", "api_key": "K", "base_url": "u"}

        expander_validation.validate_endpoint_action(action, {**action, "model_name": "m"}, "c")


class TestClientCache:
    def test_header_kwargs_make_a_hashable_cache_key(self):
        class _Fake:
            def __init__(self, api_key: str | None, **kwargs: Any) -> None:
                self.kwargs = kwargs

        first = get_or_create_client(_Fake, "k", base_url="u", default_headers={"a": "1"})
        same = get_or_create_client(_Fake, "k", base_url="u", default_headers={"a": "1"})
        other = get_or_create_client(_Fake, "k", base_url="u", default_headers={"a": "2"})
        bare = get_or_create_client(_Fake, "k", base_url="u")

        assert first is same
        assert first is not other
        assert first is not bare
        assert first.kwargs == {"base_url": "u", "default_headers": {"a": "1"}}


def _agent_config(**overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "agent_type": "classify",
        "name": "classify",
        "model_vendor": "lab",
        "model_name": "local-7b",
        "json_mode": True,
    }
    config.update(overrides)
    return config


class TestEndpointClient:
    def test_a_matching_reply_is_the_record(self, compatible):
        with FakeEndpoint() as server:
            _declare(server.base_url)
            client = compatible.endpoint_client("lab")

            records = client.invoke(_agent_config(), "Classify", {}, SCHEMA)

        assert records == [{"label": "label from local-7b", "score": 1}]
        assert server.requests[0]["headers"]["authorization"] == "Bearer no-key-required"

    def test_a_reply_that_does_not_match_the_schema_is_a_parse_error(self, compatible):
        with FakeEndpoint(mode="ignore") as server:
            _declare(server.base_url)
            client = compatible.endpoint_client("lab")

            records = client.invoke(_agent_config(), "Classify", {}, SCHEMA)

        (record,) = records
        assert record["raw_response"] == '{"wrong": 1}'
        assert record["_parse_error"].startswith(
            "endpoint 'lab' returned JSON that does not match schema 'classify'"
        )
        assert "label" in record["_parse_error"]

    def test_the_credential_goes_in_the_named_header_and_authorization_is_dropped(
        self, compatible, monkeypatch
    ):
        monkeypatch.setenv("LAB_KEY", SECRET)
        with FakeEndpoint() as server:
            load_project_endpoints(
                {
                    "endpoints": {
                        "lab": {
                            "url": server.base_url,
                            "auth": {"env": "LAB_KEY", "header": "api-key"},
                            "headers": {"X-Trace": "${LAB_KEY}-${LAB_KEY}", "api-version": "v"},
                        }
                    }
                }
            )
            compatible.endpoint_client("lab").invoke(_agent_config(), "Classify", {}, SCHEMA)

        headers = server.requests[0]["headers"]
        assert headers["api-key"] == SECRET
        assert "authorization" not in headers
        assert headers["x-trace"] == f"{SECRET}-{SECRET}"
        assert headers["api-version"] == "v"

    def test_an_inherited_base_url_and_api_key_are_ignored(self, compatible, monkeypatch):
        monkeypatch.setenv("LAB_KEY", SECRET)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-inherited-key-000000000000000")
        with FakeEndpoint() as server:
            load_project_endpoints(
                {"endpoints": {"lab": {"url": server.base_url, "auth": {"env": "LAB_KEY"}}}}
            )
            config = _agent_config(base_url="http://127.0.0.1:1/v1", api_key="OPENAI_API_KEY")

            compatible.endpoint_client("lab").invoke(config, "Classify", {}, SCHEMA)

        assert server.requests[0]["headers"]["authorization"] == f"Bearer {SECRET}"

    def test_an_unset_credential_is_refused_with_the_endpoint_named(self, compatible, monkeypatch):
        monkeypatch.delenv("LAB_KEY", raising=False)
        load_project_endpoints(
            {"endpoints": {"lab": {"url": "http://127.0.0.1:1/v1", "auth": {"env": "LAB_KEY"}}}}
        )

        with pytest.raises(ConfigValidationError) as info:
            compatible.endpoint_client("lab").invoke(_agent_config(), "Classify", {}, SCHEMA)

        assert info.value.context["reason"] == "endpoint 'lab' reads LAB_KEY, which is not set"

    def test_plain_text_mode_is_refused(self, compatible):
        _declare("http://127.0.0.1:1/v1")

        with pytest.raises(ConfigValidationError) as info:
            compatible.endpoint_client("lab").invoke(_agent_config(json_mode=False), "C", {}, None)

        assert "structured output only" in info.value.context["reason"]

    def test_every_secret_the_client_reads_is_redacted_afterwards(self, compatible, monkeypatch):
        monkeypatch.setenv("LAB_KEY", SECRET)
        monkeypatch.setenv("LAB_TRACE", "trace-value-xyz-1234567890")
        with FakeEndpoint() as server:
            load_project_endpoints(
                {
                    "endpoints": {
                        "lab": {
                            "url": server.base_url,
                            "auth": {"env": "LAB_KEY"},
                            "headers": {"X-Trace": "${LAB_TRACE}"},
                        }
                    }
                }
            )
            compatible.endpoint_client("lab").invoke(_agent_config(), "Classify", {}, SCHEMA)

        assert redact_text(f"sent {SECRET} and trace-value-xyz-1234567890 to lab") == (
            "sent [REDACTED] and [REDACTED] to lab"
        )
        record = logging.LogRecord("t", logging.INFO, "t.py", 1, f"key {SECRET}", (), None)
        RedactingFilter().filter(record)
        assert record.msg == "key [REDACTED]"
        assert redact_text("short values stay") == "short values stay"
