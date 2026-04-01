"""Resolves and caches batch clients based on configuration or batch ID."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from pydantic import SecretStr

logger = logging.getLogger(__name__)

from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.batch_base import BaseBatchClient
from agent_actions.llm.providers.batch_client_factory import BatchClientFactory
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.cache_events import CacheHitEvent, CacheMissEvent


class BatchClientResolver:
    """Resolves and caches batch clients from agent config or batch registry."""

    def __init__(
        self,
        client_cache: dict[str, BaseBatchClient] | None = None,
        default_client: BaseBatchClient | None = None,
    ):
        """
        Initialize client resolver.

        Args:
            client_cache: Optional existing client cache
            default_client: Optional default client to use as fallback
        """
        self._client_cache = client_cache if client_cache is not None else {}
        self._default_client = default_client

    def get_for_config(self, agent_config: dict[str, Any]) -> BaseBatchClient:
        """
        Get the appropriate client based on agent configuration.

        Args:
            agent_config: Agent configuration dictionary (must be resolved via hierarchy)

        Returns:
            BaseBatchClient instance for the specified client type

        Raises:
            ConfigurationError: If config is invalid or client creation fails
        """
        vendor = agent_config.get("model_vendor", "").lower()
        required_fields = ["model_vendor", "model_name"]

        missing = [f for f in required_fields if not agent_config.get(f)]
        if missing:
            raise ConfigurationError(
                f"Batch service received incomplete config (missing: {', '.join(missing)})",
                context={
                    "missing_fields": missing,
                    "agent_type": agent_config.get("agent_type", "unknown"),
                    "hint": (
                        "Caller must resolve config hierarchy "
                        "(project → workflow → action) before calling batch service"
                    ),
                },
            )

        client_type = vendor

        if client_type == "tool":
            raise ConfigurationError(
                "'tool' vendor does not support batch processing",
                context={
                    "client_type": client_type,
                    "supported_clients": ["openai", "gemini", "anthropic", "groq", "mistral"],
                },
            )

        cache_key = self._build_cache_key(client_type, agent_config)

        if cache_key in self._client_cache:
            fire_event(CacheHitEvent(cache_type="batch_client", key=f"config:{cache_key}"))
            return self._client_cache[cache_key]

        fire_event(
            CacheMissEvent(
                cache_type="batch_client", key=f"config:{cache_key}", reason="client not cached"
            )
        )

        try:
            client_config = {}
            if client_type == "gemini" and agent_config.get("gemini_api_key"):
                client_config["api_key"] = agent_config["gemini_api_key"]
            elif client_type == "openai" and agent_config.get("openai_api_key"):
                client_config["api_key"] = agent_config["openai_api_key"]

            client = BatchClientFactory.create_client(client_type, client_config)

            is_valid, error_msg = client.validate_config(agent_config)
            if not is_valid:
                raise ConfigurationError(
                    "Client configuration validation failed",
                    context={"client_type": client_type, "error_message": error_msg},
                )

            self._client_cache[cache_key] = client
            return client

        except ConfigurationError:
            raise
        except Exception as e:
            raise ConfigurationError(
                f"Failed to create client for batch_client_{client_type}: {e}",
                context={"client_type": client_type},
                cause=e,
            ) from e

    def get_for_batch_id(
        self, batch_id: str, registry_manager, output_directory: str | None = None
    ) -> BaseBatchClient:
        """
        Get the client that was used for a specific batch ID.

        Looks up the client type from the batch registry and returns
        a client instance (cached if available).

        Args:
            batch_id: The batch job ID
            registry_manager: BatchRegistryManager instance to lookup batch info
            output_directory: Output directory (used as fallback when
                registry_manager is None)

        Returns:
            BaseBatchClient instance

        Raises:
            ConfigurationError: If client cannot be determined
        """
        client_type = self._resolve_client_type(batch_id, registry_manager, output_directory)

        if client_type:
            cached = self._find_cached_client(client_type)
            if cached is not None:
                fire_event(CacheHitEvent(cache_type="batch_client", key=f"batch_id:{batch_id}"))
                return cached

            fire_event(
                CacheMissEvent(
                    cache_type="batch_client",
                    key=f"batch_id:{batch_id}",
                    reason="client not cached",
                )
            )
            return BatchClientFactory.create_client(client_type)

        if self._default_client:
            return self._default_client

        raise ConfigurationError(
            f"Cannot determine client for batch_id {batch_id}",
            context={"batch_id": batch_id, "output_directory": output_directory},
        )

    def _find_cached_client(self, client_type: str) -> BaseBatchClient | None:
        if client_type in self._client_cache:
            return self._client_cache[client_type]
        # When cache uses hashed keys (vendor:hash), return a match only if
        # there is exactly one entry for this vendor. With multiple entries
        # we cannot determine which API key was used at submission time, so
        # we return None to force a fresh (env-key) client instead of
        # silently picking the wrong one.
        prefix = f"{client_type}:"
        matches = [v for k, v in self._client_cache.items() if k.startswith(prefix)]
        if len(matches) == 1:
            return matches[0]
        return None

    @staticmethod
    def _build_cache_key(client_type: str, agent_config: dict[str, Any]) -> str:
        _raw = agent_config.get("api_key") or agent_config.get(f"{client_type}_api_key") or ""
        api_key = _raw.get_secret_value() if isinstance(_raw, SecretStr) else _raw
        if api_key:
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:12]
            return f"{client_type}:{key_hash}"
        return client_type

    def _resolve_client_type(
        self, batch_id: str, registry_manager, output_directory: str | None
    ) -> str | None:
        if registry_manager:
            entry = registry_manager.get_batch_job_by_id(batch_id)
            if entry:
                return entry.provider  # type: ignore[no-any-return]

        if output_directory:
            client_type = self._lookup_client_from_file(batch_id, output_directory)
            if client_type:
                return client_type

        return None

    def _lookup_client_from_file(self, batch_id: str, output_directory: str) -> str | None:
        registry_file = Path(output_directory) / "batch" / ".batch_registry.json"
        if not registry_file.exists():
            return None

        try:
            with open(registry_file, encoding="utf-8") as f:
                registry = json.load(f)

            for entry in registry.values():
                if entry.get("batch_id") == batch_id:
                    return entry.get("provider")  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError, KeyError):
            logger.debug("Failed to read batch registry file %s", registry_file, exc_info=True)

        return None
