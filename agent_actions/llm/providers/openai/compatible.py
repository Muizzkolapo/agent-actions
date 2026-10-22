"""OpenAI client bound to a named runtime profile (llamafile and the like).

One class per row of ``RUNTIME_PROFILES``, built from the row: the runtime's default
URL, its key rule and its measured capabilities. Requests, prompts and usage stay
the OpenAI client's own.
"""

from typing import Any, ClassVar

from agent_actions.llm.config.runtime_profiles import (
    NO_KEY_PLACEHOLDER,
    RUNTIME_PROFILES,
    RuntimeProfile,
)
from agent_actions.llm.providers.openai.client import OpenAIClient


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
        {"PROFILE": profile, "CAPABILITIES": capabilities},
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
