"""Named OpenAI-compatible runtimes, one measured profile per vendor name.

A profile is data: the runtime speaks an existing wire format, so it reuses that
format's client, prompt style, usage shape and schema dialect. Every value in a row
comes from a probe of a real server; ``verified_with`` names the build measured.
"""

from dataclasses import dataclass
from typing import Literal

Wire = Literal["openai_chat"]

# The SDK refuses an empty key; a runtime that needs none is sent this instead.
NO_KEY_PLACEHOLDER = "no-key-required"


@dataclass(frozen=True)
class RuntimeProfile:
    wire: Wire
    default_base_url: str
    api_key_required: bool
    supports_batch: bool
    supports_tools: bool
    enforces_json_schema: bool
    enforces_json_object: bool
    verified_with: str


RUNTIME_PROFILES: dict[str, RuntimeProfile] = {
    "llamafile": RuntimeProfile(
        wire="openai_chat",
        default_base_url="http://localhost:8080/v1",
        api_key_required=False,
        supports_batch=False,
        supports_tools=True,
        enforces_json_schema=True,
        enforces_json_object=False,
        verified_with="llamafile 0.10.6",
    ),
}

# The vendor whose client and formats a wire format already uses.
_WIRE_VENDOR: dict[Wire, str] = {"openai_chat": "openai"}


def wire_vendor(vendor: str) -> str:
    """The vendor whose formats *vendor* speaks: itself, unless it is a profile or an endpoint."""
    from agent_actions.llm.config.endpoints import project_endpoint

    name = vendor.lower()
    profile = RUNTIME_PROFILES.get(name)
    if profile is not None:
        return _WIRE_VENDOR[profile.wire]
    return _WIRE_VENDOR["openai_chat"] if project_endpoint(name) is not None else vendor
