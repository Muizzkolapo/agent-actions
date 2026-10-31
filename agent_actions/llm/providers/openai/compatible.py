"""OpenAI client bound to a named runtime profile (llamafile) or to a declared endpoint.

One class per row of ``RUNTIME_PROFILES``, built from the row: the runtime's default
URL, its key rule and its measured capabilities. A declared endpoint (the ``endpoints:``
block of agent_actions.yml) gets one class too, built from its row at the first call.
Requests, prompts and usage stay the OpenAI client's own; an endpoint adds its URL,
headers, timeout and credential, and fails a reply that does not match the schema.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from typing import Any, ClassVar, NoReturn

from openai import Omit

from agent_actions.errors import ConfigurationError, ConfigValidationError
from agent_actions.llm.config.endpoints import AUTHORIZATION_HEADER, Endpoint, project_endpoint
from agent_actions.llm.config.runtime_profiles import (
    NO_KEY_PLACEHOLDER,
    RUNTIME_PROFILES,
    RuntimeProfile,
)
from agent_actions.llm.providers.openai.client import OpenAIClient
from agent_actions.logging.filters import register_secret
from agent_actions.utils.constants import JSON_MODE_KEY

logger = logging.getLogger(__name__)


class RuntimeProfileClient(OpenAIClient):
    PROFILE: ClassVar[RuntimeProfile]

    @classmethod
    def get_api_key(cls, agent_config: dict[str, Any]) -> str | None:
        # An inherited api_key (often OPENAI_API_KEY from project defaults) must
        # never reach a runtime that takes no key.
        if not cls.PROFILE.api_key_required:
            return NO_KEY_PLACEHOLDER
        return OpenAIClient.get_api_key(agent_config)

    @classmethod
    def invoke(
        cls,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
        schema: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        config = {
            **agent_config,
            "base_url": agent_config.get("base_url") or cls.PROFILE.default_base_url,
        }
        return super().invoke(config, prompt_config, context_data, schema)


def _client_for(vendor: str, profile: RuntimeProfile) -> type[RuntimeProfileClient]:
    capabilities = {
        **OpenAIClient.CAPABILITIES,
        "supports_batch": profile.supports_batch,
        "supports_tools": profile.supports_tools,
        "supports_vision": False,
    }
    return type(
        f"{vendor.title()}Client",
        (RuntimeProfileClient,),
        {"PROFILE": profile, "VENDOR": vendor, "CAPABILITIES": capabilities},
    )


PROFILE_CLIENTS: dict[str, type[RuntimeProfileClient]] = {
    vendor: _client_for(vendor, profile) for vendor, profile in RUNTIME_PROFILES.items()
}


def __getattr__(name: str) -> type[RuntimeProfileClient]:
    """Let the client registry name a profile client as ``compatible:<vendor>``."""
    try:
        return PROFILE_CLIENTS[name]
    except KeyError:
        raise AttributeError(name) from None


# ── Declared endpoints ────────────────────────────────────────────────

ENDPOINT_CAPABILITIES: dict[str, Any] = {
    **OpenAIClient.CAPABILITIES,
    "supports_batch": False,
    "supports_tools": False,
    "supports_vision": False,
    "optional_fields": ["temperature", "max_tokens"],
}

# The SDK drops a default header whose value is this sentinel.
_OMIT = Omit()
_HEADER_ENV_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_COMMAND_TIMEOUT_SECONDS = 30
_COMMAND_SECRETS: dict[str, tuple[str, float]] = {}


class EndpointClient(OpenAIClient):
    """The OpenAI client sent to one declared endpoint with that endpoint's credential."""

    ENDPOINT: ClassVar[Endpoint]
    CAPABILITIES: ClassVar[dict[str, Any]] = ENDPOINT_CAPABILITIES

    @classmethod
    def invoke(
        cls,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
        schema: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if not agent_config.get(JSON_MODE_KEY, True):
            _refuse(
                cls.ENDPOINT,
                "runs with structured output only; set json_mode: true and add a schema",
            )
        return super().invoke(agent_config, prompt_config, context_data, schema)

    @classmethod
    def get_api_key(cls, agent_config: dict[str, Any]) -> str | None:
        """The SDK's placeholder: the credential travels as a header the client sets itself."""
        return NO_KEY_PLACEHOLDER

    @classmethod
    def _client_options(cls, agent_config: dict[str, Any]) -> dict[str, Any]:
        """The endpoint's url, headers and timeout; an inherited base_url plays no part."""
        endpoint = cls.ENDPOINT
        headers: dict[str, Any] = {
            name: _resolve_header(endpoint, name, value) for name, value in endpoint.headers.items()
        }
        auth = endpoint.auth
        if auth is not None:
            # The SDK's own Authorization header gives way to the declared one, so the
            # prefix is honoured; a user header named Authorization beside another
            # auth header stays as the user wrote it.
            headers[auth.header] = f"{auth.prefix}{_secret(endpoint)}"
            declared = {name.lower() for name in headers}
            if AUTHORIZATION_HEADER.lower() not in declared:
                headers[AUTHORIZATION_HEADER] = _OMIT
        return {
            "base_url": endpoint.resolved_url(),
            "default_headers": headers,
            "timeout": endpoint.timeout_seconds,
        }

    @classmethod
    def call_json(
        cls,
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
        schema: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        records = super().call_json(api_key, agent_config, prompt_config, context_data, schema)
        if schema is None or any(
            isinstance(record, dict) and "_parse_error" in record for record in records
        ):
            return records
        from agent_actions.validation.schema_output_validator import validate_output_against_schema

        action_name = str(agent_config.get("agent_type") or agent_config.get("name") or "")
        failures: list[str] = []
        # The base client's type says dict, but a scalar or list reply arrives as it is.
        for record in list[Any](records):
            if not isinstance(record, dict):
                failures.append(f"reply was {type(record).__name__}, expected a JSON object")
                continue
            report = validate_output_against_schema(record, schema, action_name, strict_mode=False)
            if not report.is_compliant:
                failures.extend(report.validation_errors or ["schema mismatch"])
        if not failures:
            return records
        reason = (
            f"endpoint '{cls.VENDOR}' returned JSON that does not match schema "
            f"'{schema.get('name', 'unknown')}': {'; '.join(failures)}"
        )
        # The disposition keeps only the code parse_error; the run log carries the why.
        logger.warning("[%s] %s", action_name, reason)
        returned = records[0] if len(records) == 1 else records
        return [{"raw_response": json.dumps(returned), "_parse_error": reason}]

    @classmethod
    def call_non_json(
        cls,
        api_key: str | None,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: dict[str, Any],
    ) -> list[dict[str, str]]:
        _refuse(
            cls.ENDPOINT, "runs with structured output only; set json_mode: true and add a schema"
        )


_ENDPOINT_CLIENTS: dict[tuple[str, str], type[EndpointClient]] = {}


def endpoint_client(name: str) -> type[EndpointClient]:
    """The client class for the declared endpoint *name*; one class per endpoint row."""
    endpoint = project_endpoint(name)
    if endpoint is None:
        raise ConfigurationError(
            f"No endpoint named '{name}' is declared in agent_actions.yml",
            context={"model_vendor": name, "operation": "endpoint_client"},
        )
    key = (name, endpoint.model_dump_json())
    client = _ENDPOINT_CLIENTS.get(key)
    if client is None:
        client = type(
            f"Endpoint_{name}_Client",
            (EndpointClient,),
            {"ENDPOINT": endpoint, "VENDOR": name},
        )
        _ENDPOINT_CLIENTS[key] = client
    return client


def _secret(endpoint: Endpoint) -> str:
    auth = endpoint.auth
    assert auth is not None
    if auth.env is not None:
        value = os.environ.get(auth.env, "")
        if not value:
            _refuse(endpoint, f"reads {auth.env}, which is not set")
        register_secret(value)
        return value
    assert auth.command is not None
    return _command_secret(endpoint, auth.command)


def _command_secret(endpoint: Endpoint, command: list[str]) -> str:
    """The command's output, run again once refresh_seconds have passed since the last run."""
    assert endpoint.auth is not None
    cached = _COMMAND_SECRETS.get(endpoint.name)
    refresh_after = endpoint.auth.refresh_seconds or 0
    if cached is not None and time.monotonic() - cached[1] < refresh_after:
        return cached[0]
    try:
        completed = subprocess.run(  # noqa: S603 — argv from the project config, no shell
            command, capture_output=True, text=True, timeout=_COMMAND_TIMEOUT_SECONDS, check=False
        )
    except FileNotFoundError:
        _refuse(endpoint, f"auth command '{command[0]}' is not on PATH")
    except subprocess.TimeoutExpired:
        _refuse(
            endpoint, f"auth command '{command[0]}' did not finish in {_COMMAND_TIMEOUT_SECONDS}s"
        )
    except OSError as exc:
        _refuse(endpoint, f"auth command '{command[0]}' could not be run: {exc.strerror}")
    # stderr stays out of the message: it can hold the secret.
    if completed.returncode != 0:
        _refuse(endpoint, f"auth command '{command[0]}' exited with {completed.returncode}")
    value = completed.stdout.strip()
    if not value:
        _refuse(endpoint, f"auth command '{command[0]}' printed nothing")
    register_secret(value)
    _COMMAND_SECRETS[endpoint.name] = (value, time.monotonic())
    return value


def clear_command_secrets() -> None:
    _COMMAND_SECRETS.clear()


def _resolve_header(endpoint: Endpoint, header: str, value: str) -> str:
    def substitute(match: re.Match[str]) -> str:
        variable = match.group(1)
        resolved = os.environ.get(variable, "")
        if not resolved:
            _refuse(endpoint, f"reads {variable} for header {header}, which is not set")
        register_secret(resolved)
        return resolved

    return _HEADER_ENV_VAR.sub(substitute, value)


def _refuse(endpoint: Endpoint, text: str) -> NoReturn:
    raise ConfigValidationError("endpoints", f"endpoint '{endpoint.name}' {text}")
