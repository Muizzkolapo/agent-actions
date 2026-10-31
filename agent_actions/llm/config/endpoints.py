"""User-declared OpenAI-compatible endpoints: the `endpoints:` block of agent_actions.yml.

An endpoint is a runtime profile the user writes: a base URL, a credential source and
extra headers. The block is validated when the project config loads, with the endpoint
name and the key in every refusal. The loaded endpoints form a per-project registry
that the next project load replaces, so nothing declared by one project reaches another.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any, NoReturn

from pydantic import BaseModel, ConfigDict, ValidationError

from agent_actions.errors import ConfigValidationError
from agent_actions.llm.config.runtime_profiles import RUNTIME_PROFILES
from agent_actions.llm.config.vendor import VENDOR_ALIASES, VendorType

DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_REFRESH_SECONDS = 3000
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_WHOLE_ENV_VAR = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
_CREDENTIAL_WORDS = ("authorization", "key", "token", "secret")
_CHAT_COMPLETIONS = "/chat/completions"
_URL_HINT = f"give the base URL, for example http://gpu-box:8000/v1; agac adds {_CHAT_COMPLETIONS}"


class EndpointAuth(BaseModel):
    """Where an endpoint's credential comes from and which header carries it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    env: str | None = None
    command: list[str] | None = None
    refresh_seconds: int | None = None
    header: str = AUTHORIZATION_HEADER
    prefix: str | None = None


class Endpoint(BaseModel):
    """One validated entry of the `endpoints:` block. `auth` is None for `auth: none`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    url: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    auth: EndpointAuth | None = None
    headers: dict[str, str] = {}

    @property
    def url_env_var(self) -> str | None:
        """The variable a `${NAME}` url reads, or None for a literal url."""
        match = _WHOLE_ENV_VAR.match(self.url)
        return match.group(1) if match else None

    def resolved_url(self, environ: Mapping[str, str] = os.environ) -> str:
        """The base URL to send requests to, read from the environment for a `${NAME}` url."""
        variable = self.url_env_var
        if variable is None:
            return self.url
        value = environ.get(variable, "")
        if not value:
            raise ConfigValidationError(
                "endpoints",
                f"endpoint '{self.name}' reads its url from {variable}, which is not set",
            )
        _check_literal_url(f"endpoints.{self.name}.url", value)
        return value


def builtin_vendor_names() -> frozenset[str]:
    """Every name an endpoint must not take: the vendor types, their aliases and the profiles."""
    return frozenset([v.value for v in VendorType] + list(VENDOR_ALIASES) + list(RUNTIME_PROFILES))


def parse_endpoints(raw: Any) -> dict[str, Endpoint]:
    """Validate the `endpoints:` block, refusing the first mistake with its key and text."""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        _refuse("endpoints", "must be a mapping of endpoint name to its settings")
    return {str(name): _parse_endpoint(str(name), settings) for name, settings in raw.items()}


def _parse_endpoint(name: str, settings: Any) -> Endpoint:
    key = f"endpoints.{name}"
    if name in builtin_vendor_names():
        _refuse(key, f"'{name}' is a built-in vendor; choose another endpoint name")
    if not _NAME.match(name):
        _refuse(key, "use a lowercase name of letters, digits, '-' and '_'")
    if not isinstance(settings, Mapping):
        _refuse(key, "must be a mapping with url and auth")
    if "auth" not in settings:
        _refuse(
            key, "auth is required; write 'auth: none' for an endpoint that takes no credential"
        )
    if "name" in settings:
        _refuse(key, "unknown key 'name'")

    fields = dict(settings)
    fields["auth"] = _parse_auth(f"{key}.auth", fields["auth"])
    try:
        endpoint = Endpoint(name=name, **fields)
    except ValidationError as exc:
        _refuse_pydantic(key, exc)

    if endpoint.timeout_seconds <= 0:
        _refuse(f"{key}.timeout_seconds", "must be greater than 0")
    if endpoint.url_env_var is None:
        _check_url_shape(f"{key}.url", endpoint.url)
    _check_headers(key, endpoint)
    return endpoint


def _parse_auth(key: str, raw: Any) -> EndpointAuth | None:
    if raw == "none":
        return None
    if not isinstance(raw, Mapping):
        _refuse(key, "write 'auth: none', or a mapping with env or command")
    try:
        auth = EndpointAuth(**raw)
    except ValidationError as exc:
        _refuse_pydantic(key, exc)

    if (auth.env is None) == (auth.command is None):
        _refuse(key, "give exactly one of env or command, or write 'auth: none'")
    if auth.refresh_seconds is not None and auth.command is None:
        _refuse(key, "refresh_seconds applies to command auth only")

    is_authorization = auth.header.lower() == AUTHORIZATION_HEADER.lower()
    return auth.model_copy(
        update={
            "refresh_seconds": (
                auth.refresh_seconds
                if auth.refresh_seconds is not None or auth.command is None
                else DEFAULT_REFRESH_SECONDS
            ),
            "prefix": (BEARER_PREFIX if is_authorization else "")
            if auth.prefix is None
            else auth.prefix,
        }
    )


def _check_url_shape(key: str, url: str) -> None:
    if "${" in url:
        _refuse(key, "write the whole URL as one ${ENV_VAR}, or as a literal URL")
    _check_literal_url(key, url)


def _check_literal_url(key: str, url: str) -> None:
    if not url.startswith(("http://", "https://")):
        _refuse(key, "must start with http:// or https://")
    if url.rstrip("/").endswith(_CHAT_COMPLETIONS):
        _refuse(key, _URL_HINT)


def _check_headers(key: str, endpoint: Endpoint) -> None:
    # `auth: none` still sends the SDK's placeholder key in Authorization.
    auth_header = (endpoint.auth.header if endpoint.auth else AUTHORIZATION_HEADER).lower()
    for header, value in endpoint.headers.items():
        header_key = f"{key}.headers.{header}"
        if header.lower() == auth_header:
            _refuse(header_key, "this header is set by auth; remove it from headers")
        looks_like_credential = any(word in header.lower() for word in _CREDENTIAL_WORDS)
        if looks_like_credential and "${" not in value:
            _refuse(header_key, "write a credential as ${ENV_VAR}, not as a literal value")


def _refuse_pydantic(key: str, exc: ValidationError) -> NoReturn:
    error = exc.errors()[0]
    path = [str(part) for part in error["loc"]]
    if error["type"] == "extra_forbidden":
        _refuse(".".join([key, *path[:-1]]), f"unknown key '{path[-1]}'")
    if error["type"] == "missing":
        _refuse(".".join([key, *path[:-1]]), f"{path[-1]} is required")
    _refuse(".".join([key, *path]), error["msg"])


def _refuse(key: str, text: str) -> NoReturn:
    raise ConfigValidationError("endpoints", f"{key}: {text}")


# ── Per-project registry ──────────────────────────────────────────────

_PROJECT_ENDPOINTS: dict[str, Endpoint] = {}


def set_project_endpoints(endpoints: Mapping[str, Endpoint]) -> None:
    """Replace the registry with the endpoints of the project whose config just loaded."""
    _PROJECT_ENDPOINTS.clear()
    _PROJECT_ENDPOINTS.update(endpoints)


def project_endpoints() -> dict[str, Endpoint]:
    return dict(_PROJECT_ENDPOINTS)


def project_endpoint(name: str) -> Endpoint | None:
    return _PROJECT_ENDPOINTS.get(name)


def clear_project_endpoints() -> None:
    _PROJECT_ENDPOINTS.clear()
