"""One structured-output request to a declared endpoint, for `--verify-keys`.

A server cannot say whether it honours `response_format: json_schema`; one request with a
one-field schema proves it. A pass proves a small schema is honoured, not every schema:
the client's own check on each reply stays the guard at run time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from agent_actions.errors import ConfigurationError, NetworkError, VendorAPIError
from agent_actions.llm.providers.openai.compatible import endpoint_client

PROBE_SCHEMA: dict[str, Any] = {
    "name": "agac_probe",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    },
}
PROBE_PROMPT = 'Reply with the JSON object {"ok": true} and nothing else.'
PROBE_MAX_TOKENS = 16
NOT_HONOURED = (
    "does not honour response_format json_schema; "
    "agac supports only endpoints with OpenAI structured output"
)

Kind = Literal["ok", "refused", "not_honoured", "answered", "unreachable", "config"]


@dataclass(frozen=True)
class EndpointProbeResult:
    name: str
    kind: Kind
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.kind == "ok"


def probe_endpoint(name: str, model_name: str) -> EndpointProbeResult:
    """Send the probe to endpoint *name* as *model_name* and judge the reply."""
    config = {
        "agent_type": "agac_probe",
        "name": "agac_probe",
        "model_vendor": name,
        "model_name": model_name,
        "json_mode": True,
        "max_tokens": PROBE_MAX_TOKENS,
    }
    try:
        records = endpoint_client(name).invoke(config, PROBE_PROMPT, {}, PROBE_SCHEMA)
    except (VendorAPIError, NetworkError) as exc:
        return _judge_error(name, exc)
    except ConfigurationError as exc:
        return EndpointProbeResult(name, "config", str(exc.context.get("reason") or exc))

    if len(records) == 1 and records[0] in ({"ok": True}, {"ok": False}):
        return EndpointProbeResult(name, "ok")
    return EndpointProbeResult(name, "not_honoured", f"endpoint '{name}' {NOT_HONOURED}")


def _judge_error(name: str, exc: Exception) -> EndpointProbeResult:
    status = getattr(exc.__cause__, "status_code", None)
    if status in (401, 403):
        return EndpointProbeResult(
            name, "refused", f"endpoint '{name}' refused the credential (HTTP {status})"
        )
    if status in (400, 422):
        # The usual way a server declines response_format: it rejects the request.
        return EndpointProbeResult(
            name, "not_honoured", f"endpoint '{name}' {NOT_HONOURED} (HTTP {status}: {exc})"
        )
    if status is not None:
        return EndpointProbeResult(
            name, "answered", f"endpoint '{name}' answered HTTP {status}: {exc}"
        )
    return EndpointProbeResult(
        name, "unreachable", f"endpoint '{name}' could not be reached: {exc}"
    )
