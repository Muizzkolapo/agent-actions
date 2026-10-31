"""One structured-output request to a declared endpoint, for `--verify-keys`.

A server cannot say whether it honours `response_format: json_schema`; one request with a
one-field schema proves it. A pass proves a small schema is honoured, not every schema:
the client's own check on each reply stays the guard at run time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True)
class EndpointProbeResult:
    name: str
    ok: bool
    error: str | None = None


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
    except VendorAPIError as exc:
        status = getattr(exc.__cause__, "status_code", None)
        if status in (401, 403):
            return EndpointProbeResult(
                name, False, f"endpoint '{name}' refused the credential (HTTP {status})"
            )
        return EndpointProbeResult(name, False, f"endpoint '{name}' answered an error: {exc}")
    except NetworkError as exc:
        return EndpointProbeResult(name, False, f"endpoint '{name}' could not be reached: {exc}")
    except ConfigurationError as exc:
        return EndpointProbeResult(name, False, str(exc.context.get("reason") or exc))

    honoured = len(records) == 1 and records[0] in ({"ok": True}, {"ok": False})
    if honoured:
        return EndpointProbeResult(name, True)
    return EndpointProbeResult(
        name,
        False,
        f"endpoint '{name}' does not honour response_format json_schema; "
        "agac supports only endpoints with OpenAI structured output",
    )
