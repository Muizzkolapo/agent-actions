"""A declared endpoint is a vendor: in every vendor list, with the OpenAI formats and client.

The endpoint client keeps the OpenAI client's requests and parsing; it adds the
endpoint's URL, headers, timeout and credential, fails a reply that does not match
the schema, and registers every secret it reads with the redactor.
"""

from __future__ import annotations

import importlib
import logging
import pathlib
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
        monkeypatch.setenv("LAB_TRACE_TOKEN", "trace-value-xyz-1234567890")
        with FakeEndpoint() as server:
            load_project_endpoints(
                {
                    "endpoints": {
                        "lab": {
                            "url": server.base_url,
                            "auth": {"env": "LAB_KEY"},
                            "headers": {"X-Trace": "${LAB_TRACE_TOKEN}"},
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


def _declare_full(server_url: str, **endpoint: Any) -> None:
    load_project_endpoints({"endpoints": {"lab": {"url": server_url, **endpoint}}})


class TestCredentialHeaders:
    def test_a_prefix_on_authorization_is_honoured(self, compatible, monkeypatch):
        monkeypatch.setenv("LAB_KEY", SECRET)
        with FakeEndpoint() as server:
            _declare_full(server.base_url, auth={"env": "LAB_KEY", "prefix": "Token "})
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert server.requests[0]["headers"]["authorization"] == f"Token {SECRET}"

    def test_an_empty_prefix_sends_the_bare_secret(self, compatible, monkeypatch):
        monkeypatch.setenv("LAB_KEY", SECRET)
        with FakeEndpoint() as server:
            _declare_full(server.base_url, auth={"env": "LAB_KEY", "prefix": ""})
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert server.requests[0]["headers"]["authorization"] == SECRET

    def test_a_user_authorization_header_beside_a_named_auth_header_is_kept(
        self, compatible, monkeypatch
    ):
        monkeypatch.setenv("LAB_KEY", SECRET)
        monkeypatch.setenv("USER_JWT", "user-jwt-value-1234567890")
        with FakeEndpoint() as server:
            _declare_full(
                server.base_url,
                auth={"env": "LAB_KEY", "header": "X-Api-Key"},
                headers={"Authorization": "${USER_JWT}"},
            )
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        headers = server.requests[0]["headers"]
        assert headers["x-api-key"] == SECRET
        assert headers["authorization"] == "user-jwt-value-1234567890"

    def test_the_timeout_reaches_the_request(self, compatible):
        with FakeEndpoint() as server:
            _declare_full(server.base_url, auth="none", timeout_seconds=5)
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert server.requests[0]["headers"]["x-stainless-read-timeout"].startswith("5")


class TestReplyShapes:
    @pytest.mark.parametrize(
        ("content", "fragment"),
        [
            ("42", "reply was int, expected a JSON object"),
            ("null", "expected a JSON object"),
            ('[{"label": "a", "score": 1}, 2]', "reply was int, expected a JSON object"),
        ],
        ids=["scalar", "null", "list-with-a-scalar"],
    )
    def test_a_reply_that_is_not_an_object_is_a_parse_error(self, compatible, content, fragment):
        with FakeEndpoint() as server:
            server.content = content
            _declare(server.base_url)

            (record,) = compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert record["_parse_error"].startswith("endpoint 'lab' returned JSON that does not match")
        assert fragment in record["_parse_error"]

    def test_an_extra_field_is_refused_by_a_closed_schema_and_kept_by_an_open_one(self, compatible):
        closed = SCHEMA
        open_schema = {
            "name": "classify",
            "schema": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "score": {"type": "integer"}},
                "required": ["label", "score"],
            },
        }
        with FakeEndpoint() as server:
            server.content = '{"label": "a", "score": 1, "extra": true}'
            _declare(server.base_url)
            client = compatible.endpoint_client("lab")

            (refused,) = client.invoke(_agent_config(), "C", {}, closed)
            (kept,) = client.invoke(_agent_config(), "C", {}, open_schema)

        assert "extra" in refused["_parse_error"]
        assert kept == {"label": "a", "score": 1, "extra": True}


class TestCommandAuth:
    def test_the_command_output_is_the_credential(self, compatible):
        with FakeEndpoint() as server:
            _declare_full(
                server.base_url,
                auth={"command": ["python3", "-c", "print('cmd-token-value-123456')"]},
            )
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert server.requests[0]["headers"]["authorization"] == "Bearer cmd-token-value-123456"
        assert redact_text("saw cmd-token-value-123456") == "saw [REDACTED]"

    def test_the_command_runs_once_until_refresh_seconds_pass(
        self, compatible, tmp_path, monkeypatch
    ):
        counter = tmp_path / "runs"
        counter.write_text("0")
        script = (
            f"import pathlib; p = pathlib.Path({str(counter)!r}); n = int(p.read_text()) + 1; "
            "p.write_text(str(n)); print(f'token-number-{n}-abcdef')"
        )
        with FakeEndpoint() as server:
            _declare_full(
                server.base_url, auth={"command": ["python3", "-c", script], "refresh_seconds": 60}
            )
            client = compatible.endpoint_client("lab")
            now = [1000.0]
            monkeypatch.setattr(compatible.time, "monotonic", lambda: now[0])

            client.invoke(_agent_config(), "C", {}, SCHEMA)
            now[0] += 30
            client.invoke(_agent_config(), "C", {}, SCHEMA)
            now[0] += 31
            client.invoke(_agent_config(), "C", {}, SCHEMA)

        sent = [r["headers"]["authorization"] for r in server.requests]
        assert sent == [
            "Bearer token-number-1-abcdef",
            "Bearer token-number-1-abcdef",
            "Bearer token-number-2-abcdef",
        ]
        assert counter.read_text() == "2"

    def test_a_failing_command_is_refused_without_its_stderr(self, compatible):
        _declare_full(
            "http://127.0.0.1:1/v1",
            auth={
                "command": [
                    "python3",
                    "-c",
                    "import sys; print('leaked-secret-stderr', file=sys.stderr); sys.exit(3)",
                ]
            },
        )

        with pytest.raises(ConfigValidationError) as info:
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert info.value.context["reason"] == "endpoint 'lab' auth command 'python3' exited with 3"
        assert "leaked" not in str(info.value)

    def test_a_command_that_cannot_run_is_refused(self, compatible, tmp_path):
        not_executable = tmp_path / "token.txt"
        not_executable.write_text("x")
        _declare_full("http://127.0.0.1:1/v1", auth={"command": [str(not_executable)]})

        with pytest.raises(ConfigValidationError) as info:
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert info.value.context["reason"].startswith(
            f"endpoint 'lab' auth command '{not_executable}' could not be run: "
        )


class TestRedactionRules:
    def test_a_short_header_value_is_not_masked_by_value(self, compatible, monkeypatch):
        monkeypatch.setenv("SHORT", "v")
        with FakeEndpoint() as server:
            _declare_full(server.base_url, auth="none", headers={"api-version": "${SHORT}"})
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert server.requests[0]["headers"]["api-version"] == "v"
        assert redact_text("v is a letter in every log line") == "v is a letter in every log line"

    def test_a_vendor_error_that_echoes_the_request_is_masked_where_it_is_wrapped(
        self, compatible, monkeypatch
    ):
        from agent_actions.errors import VendorAPIError

        monkeypatch.setenv("LAB_KEY", SECRET)
        with FakeEndpoint(statuses=[401], echo_headers=True) as server:
            _declare_full(server.base_url, auth={"env": "LAB_KEY", "header": "api-key"})

            with pytest.raises(VendorAPIError) as info:
                compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert SECRET not in str(info.value)
        assert "[REDACTED]" in str(info.value)  # the echo reached the message, masked
        assert SECRET in server.requests[0]["headers"]["api-key"]  # and it was sent

    def test_the_cli_error_block_masks_a_registered_value_in_the_root_cause(self):
        """The translator walks to the root cause, whose text wrap_vendor_error never saw."""
        from agent_actions.errors import VendorAPIError
        from agent_actions.logging.errors import format_user_error
        from agent_actions.logging.filters import register_secret

        root = RuntimeError(f"gateway said: api-key {SECRET} refused")
        wrapped = VendorAPIError("lab API error", cause=root)

        shown_before = format_user_error(wrapped)
        register_secret(SECRET)
        shown_after = format_user_error(wrapped)

        assert SECRET in shown_before  # the root text is what this path prints
        assert SECRET not in shown_after
        assert "[REDACTED]" in shown_after

    def test_a_server_text_that_names_a_key_is_not_mangled(self, compatible, monkeypatch):
        from agent_actions.errors import VendorAPIError

        monkeypatch.setenv("LAB_KEY", SECRET)
        with FakeEndpoint(statuses=[400]) as server:
            server.error_message = "Invalid value for api_key: expected a string"
            _declare_full(server.base_url, auth={"env": "LAB_KEY"})
            with pytest.raises(VendorAPIError) as info:
                compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert "Invalid value for api_key: expected a string" in str(info.value)

    def test_a_non_credential_header_value_is_not_registered(self, compatible, monkeypatch):
        monkeypatch.setenv("REGION", "us-east-1-region")
        with FakeEndpoint() as server:
            _declare_full(server.base_url, auth="none", headers={"X-Region": "${REGION}"})
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert server.requests[0]["headers"]["x-region"] == "us-east-1-region"
        assert redact_text("connect to us-east-1-region") == "connect to us-east-1-region"


class TestOneAuthorizationHeader:
    @pytest.mark.parametrize("spelling", ["authorization", "AUTHORIZATION", "Authorization"])
    def test_the_auth_header_in_any_spelling_is_sent_once(self, compatible, monkeypatch, spelling):
        monkeypatch.setenv("LAB_KEY", SECRET)
        with FakeEndpoint() as server:
            _declare_full(server.base_url, auth={"env": "LAB_KEY", "header": spelling})
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        sent = [v for k, v in server.requests[0]["raw_headers"] if k == "authorization"]
        assert sent == [f"Bearer {SECRET}"]

    def test_a_user_authorization_header_in_lower_case_is_sent_once(self, compatible, monkeypatch):
        monkeypatch.setenv("LAB_KEY", SECRET)
        monkeypatch.setenv("USER_JWT", "user-jwt-value-1234567890")
        with FakeEndpoint() as server:
            _declare_full(
                server.base_url,
                auth={"env": "LAB_KEY", "header": "X-Api-Key"},
                headers={"authorization": "${USER_JWT}"},
            )
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        sent = [v for k, v in server.requests[0]["raw_headers"] if k == "authorization"]
        assert sent == ["user-jwt-value-1234567890"]
        assert server.requests[0]["headers"]["x-api-key"] == SECRET


class TestCommandCache:
    def test_a_changed_command_is_run_not_served_from_the_old_cache(self, compatible):
        with FakeEndpoint() as server:
            _declare_full(
                server.base_url, auth={"command": ["python3", "-c", "print('token-a-1234567')"]}
            )
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)
            _declare_full(
                server.base_url, auth={"command": ["python3", "-c", "print('token-b-1234567')"]}
            )
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        sent = [r["headers"]["authorization"] for r in server.requests]
        assert sent == ["Bearer token-a-1234567", "Bearer token-b-1234567"]


class TestHeaderSafeValues:
    def test_whitespace_around_an_exported_secret_is_trimmed(self, compatible, monkeypatch):
        monkeypatch.setenv("LAB_KEY", f"  {SECRET}\n")
        with FakeEndpoint() as server:
            _declare_full(server.base_url, auth={"env": "LAB_KEY"})
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert server.requests[0]["headers"]["authorization"] == f"Bearer {SECRET}"

    def test_a_line_break_inside_a_secret_is_refused_by_name(self, compatible, monkeypatch):
        monkeypatch.setenv("LAB_KEY", "first-half-1234\nsecond-half")
        _declare_full("http://127.0.0.1:1/v1", auth={"env": "LAB_KEY"})

        with pytest.raises(ConfigValidationError) as info:
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert info.value.context["reason"] == (
            "endpoint 'lab' reads LAB_KEY, whose value holds a line break"
        )

    def test_a_line_break_inside_a_header_value_is_refused_by_name(self, compatible, monkeypatch):
        monkeypatch.setenv("TRACE_TOKEN", "a\rb")
        _declare_full("http://127.0.0.1:1/v1", auth="none", headers={"X-Trace": "${TRACE_TOKEN}"})

        with pytest.raises(ConfigValidationError) as info:
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert info.value.context["reason"] == (
            "endpoint 'lab' reads TRACE_TOKEN for header X-Trace, whose value holds a line break"
        )

    def test_a_line_break_inside_a_command_output_is_refused_by_name(self, compatible):
        _declare_full(
            "http://127.0.0.1:1/v1",
            auth={"command": ["python3", "-c", "print('first-half-1234'); print('second')"]},
        )

        with pytest.raises(ConfigValidationError) as info:
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert info.value.context["reason"] == (
            "endpoint 'lab' runs auth command 'python3', whose value holds a line break"
        )


def _counting_command(
    counter: pathlib.Path, prefix: str = "token", sleep: float = 0.0
) -> list[str]:
    """A command that appends one line per run and prints a token numbered by that run."""
    script = (
        "import pathlib, time; "
        f"time.sleep({sleep}); p = pathlib.Path({str(counter)!r}); "
        "n = len(p.read_text().splitlines()) + 1 if p.exists() else 1; "
        "p.open('a').write('run\\n'); "
        f"print(f'{prefix}-number-{{n}}-abcdef')"
    )
    return ["python3", "-c", script]


def _runs(counter: pathlib.Path) -> int:
    return len(counter.read_text().splitlines()) if counter.exists() else 0


class TestCommandAuthRuntime:
    def test_twenty_parallel_records_run_the_command_once(self, compatible, tmp_path):
        from concurrent.futures import ThreadPoolExecutor

        counter = tmp_path / "runs"
        with FakeEndpoint() as server:
            _declare_full(server.base_url, auth={"command": _counting_command(counter, sleep=0.3)})
            client = compatible.endpoint_client("lab")
            with ThreadPoolExecutor(max_workers=20) as pool:
                results = list(
                    pool.map(lambda _: client.invoke(_agent_config(), "C", {}, SCHEMA), range(20))
                )

        assert len(results) == 20
        assert _runs(counter) == 1
        sent = {r["headers"]["authorization"] for r in server.requests}
        assert sent == {"Bearer token-number-1-abcdef"}
        assert len(server.requests) == 20

    def test_a_401_with_command_auth_refreshes_once_then_succeeds(self, compatible, tmp_path):
        counter = tmp_path / "runs"
        with FakeEndpoint(statuses=[401]) as server:
            _declare_full(server.base_url, auth={"command": _counting_command(counter)})

            records = compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert records == [{"label": "label from local-7b", "score": 1}]
        assert _runs(counter) == 2
        assert [r["headers"]["authorization"] for r in server.requests] == [
            "Bearer token-number-1-abcdef",
            "Bearer token-number-2-abcdef",
        ]

    def test_a_second_401_after_the_refresh_fails_the_call(self, compatible, tmp_path):
        from agent_actions.errors import VendorAPIError

        counter = tmp_path / "runs"
        with FakeEndpoint(statuses=[401, 401]) as server:
            _declare_full(server.base_url, auth={"command": _counting_command(counter)})

            with pytest.raises(VendorAPIError) as info:
                compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert "401" in str(info.value)
        assert _runs(counter) == 2
        assert len(server.requests) == 2

    def test_a_401_with_env_auth_is_not_retried(self, compatible, monkeypatch):
        from agent_actions.errors import VendorAPIError

        monkeypatch.setenv("LAB_KEY", SECRET)
        with FakeEndpoint(statuses=[401]) as server:
            _declare_full(server.base_url, auth={"env": "LAB_KEY"})

            with pytest.raises(VendorAPIError):
                compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert len(server.requests) == 1

    def test_each_endpoint_refreshes_on_its_own_clock(self, compatible, tmp_path, monkeypatch):
        counter_a, counter_b = tmp_path / "a", tmp_path / "b"
        with FakeEndpoint() as server:
            load_project_endpoints(
                {
                    "endpoints": {
                        "fast": {
                            "url": server.base_url,
                            "auth": {
                                "command": _counting_command(counter_a, "a"),
                                "refresh_seconds": 60,
                            },
                        },
                        "slow": {
                            "url": server.base_url,
                            "auth": {
                                "command": _counting_command(counter_b, "b"),
                                "refresh_seconds": 1000,
                            },
                        },
                    }
                }
            )
            fast, slow = compatible.endpoint_client("fast"), compatible.endpoint_client("slow")
            now = [1000.0]
            monkeypatch.setattr(compatible.time, "monotonic", lambda: now[0])

            fast.invoke(_agent_config(model_vendor="fast"), "C", {}, SCHEMA)
            slow.invoke(_agent_config(model_vendor="slow"), "C", {}, SCHEMA)
            now[0] += 61
            fast.invoke(_agent_config(model_vendor="fast"), "C", {}, SCHEMA)
            slow.invoke(_agent_config(model_vendor="slow"), "C", {}, SCHEMA)

        assert _runs(counter_a) == 2
        assert _runs(counter_b) == 1
        sent = [r["headers"]["authorization"] for r in server.requests]
        assert sent == [
            "Bearer a-number-1-abcdef",
            "Bearer b-number-1-abcdef",
            "Bearer a-number-2-abcdef",
            "Bearer b-number-1-abcdef",
        ]

    def test_the_command_runs_in_the_project_root(self, compatible, tmp_path, monkeypatch):
        (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")
        (tmp_path / "sub" / "deep").mkdir(parents=True)
        monkeypatch.chdir(tmp_path / "sub" / "deep")
        where = tmp_path / "where"
        script = f"import os, pathlib; pathlib.Path({str(where)!r}).write_text(os.getcwd()); print('cwd-token-abcdef')"
        with FakeEndpoint() as server:
            _declare_full(server.base_url, auth={"command": ["python3", "-c", script]})
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert pathlib.Path(where.read_text()).resolve() == tmp_path.resolve()

    def test_twenty_parallel_refusals_renew_the_token_once(self, compatible, tmp_path):
        from concurrent.futures import ThreadPoolExecutor

        counter = tmp_path / "runs"
        with FakeEndpoint(statuses=[401] * 20) as server:
            _declare_full(server.base_url, auth={"command": _counting_command(counter, sleep=0.2)})
            client = compatible.endpoint_client("lab")
            with ThreadPoolExecutor(max_workers=20) as pool:
                results = list(
                    pool.map(lambda _: client.invoke(_agent_config(), "C", {}, SCHEMA), range(20))
                )

        assert len(results) == 20
        assert _runs(counter) == 2
        sent = [r["headers"]["authorization"] for r in server.requests]
        assert len(sent) == 40
        assert sent.count("Bearer token-number-1-abcdef") == 20
        assert sent.count("Bearer token-number-2-abcdef") == 20

    def test_an_error_other_than_401_does_not_renew_the_token(self, compatible, tmp_path):
        from agent_actions.errors import VendorAPIError

        counter = tmp_path / "runs"
        with FakeEndpoint(statuses=[403]) as server:
            _declare_full(server.base_url, auth={"command": _counting_command(counter)})

            with pytest.raises(VendorAPIError):
                compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert _runs(counter) == 1
        assert len(server.requests) == 1

    def test_the_command_runs_in_the_nearest_project_root(self, compatible, tmp_path, monkeypatch):
        """A project installed inside another (agac example) runs its command from its own root."""
        (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")
        inner = tmp_path / "examples" / "quiz"
        (inner / "agent_workflow" / "wf").mkdir(parents=True)
        (inner / "agent_actions.yml").write_text("schema_path: schema\n")
        monkeypatch.chdir(inner / "agent_workflow" / "wf")
        where = tmp_path / "where"
        script = f"import os, pathlib; pathlib.Path({str(where)!r}).write_text(os.getcwd()); print('cwd-token-abcdef')"
        with FakeEndpoint() as server:
            _declare_full(server.base_url, auth={"command": ["python3", "-c", script]})
            compatible.endpoint_client("lab").invoke(_agent_config(), "C", {}, SCHEMA)

        assert pathlib.Path(where.read_text()).resolve() == inner.resolve()
