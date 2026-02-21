"""
Batch Client Resolver.

Handles resolution and caching of batch clients based on configuration or batch ID.
Extracted from BatchService for better separation of concerns.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

from agent_actions.llm.providers.batch_base import BaseBatchClient
from agent_actions.llm.providers.batch_client_factory import BatchClientFactory
from agent_actions.errors import ConfigurationError
from agent_actions.logging import fire_event
from agent_actions.logging.events.types import CacheHitEvent, CacheMissEvent


class BatchClientResolver:
    """
    Resolves and caches batch clients.

    Handles client instantiation from agent config or batch registry lookup.
    Maintains internal cache to avoid recreating clients.

    Example:
        resolver = BatchClientResolver()
        client = resolver.get_for_config(agent_config)
        client2 = resolver.get_for_batch_id('batch_123', output_dir, registry_manager)
    """

    def __init__(
        self,
        client_cache: Optional[Dict[str, BaseBatchClient]] = None,
        default_client: Optional[BaseBatchClient] = None,
    ):
        """
        Initialize client resolver.

        Args:
            client_cache: Optional existing client cache
            default_client: Optional default client to use as fallback
        """
        self._client_cache = client_cache if client_cache is not None else {}
        self._default_client = default_client

    def get_for_config(self, agent_config: Dict[str, Any]) -> BaseBatchClient:
        """
        Get the appropriate client based on agent configuration.

        Args:
            agent_config: Agent configuration dictionary (must be resolved via hierarchy)

        Returns:
            BaseBatchClient instance for the specified client type

        Raises:
            ConfigurationError: If config is invalid or client creation fails
        """
        # Mock client doesn't require api_key
        vendor = agent_config.get("model_vendor", "").lower()
        if vendor == "mock":
            required_fields = ["model_vendor", "model_name"]
        else:
            required_fields = ["model_vendor", "model_name", "api_key"]

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

        # Check cache
        if client_type in self._client_cache:
            fire_event(CacheHitEvent(cache_type="batch_client", key=f"config:{client_type}"))
            return self._client_cache[client_type]

        # Cache miss - need to create new client
        fire_event(
            CacheMissEvent(
                cache_type="batch_client", key=f"config:{client_type}", reason="client not cached"
            )
        )

        # Create new client
        try:
            client_config = {}
            if client_type == "gemini" and agent_config.get("gemini_api_key"):
                client_config["api_key"] = agent_config["gemini_api_key"]
            elif client_type == "openai" and agent_config.get("openai_api_key"):
                client_config["api_key"] = agent_config["openai_api_key"]

            client = BatchClientFactory.create_client(client_type, client_config)

            # Validate config
            is_valid, error_msg = client.validate_config(agent_config)
            if not is_valid:
                raise ConfigurationError(
                    "Client configuration validation failed",
                    context={"client_type": client_type, "error_message": error_msg},
                )

            # Cache and return
            self._client_cache[client_type] = client
            return client

        except Exception as e:
            raise ConfigurationError(
                f"Failed to create client for batch_client_{client_type}: {e}",
                context={"client_type": client_type},
                cause=e,
            ) from e

    def get_for_batch_id(
        self, batch_id: str, registry_manager, output_directory: Optional[str] = None
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
            # Check cache
            if client_type in self._client_cache:
                fire_event(CacheHitEvent(cache_type="batch_client", key=f"batch_id:{batch_id}"))
                return self._client_cache[client_type]

            # Cache miss - create new client
            fire_event(
                CacheMissEvent(
                    cache_type="batch_client",
                    key=f"batch_id:{batch_id}",
                    reason="client not cached",
                )
            )
            return BatchClientFactory.create_client(client_type)

        # Fallback to default client if available
        if self._default_client:
            return self._default_client

        raise ConfigurationError(
            f"Cannot determine client for batch_id {batch_id}",
            context={"batch_id": batch_id, "output_directory": output_directory},
        )

    def _resolve_client_type(
        self, batch_id: str, registry_manager, output_directory: Optional[str]
    ) -> Optional[str]:
        """Resolve client type from registry manager or registry file.

        Args:
            batch_id: The batch job ID to look up
            registry_manager: Optional registry manager instance
            output_directory: Optional output directory containing registry file

        Returns:
            Client type string or None if not found
        """
        # Try registry manager first
        if registry_manager:
            entry = registry_manager.get_batch_job_by_id(batch_id)
            if entry:
                return entry.provider

        # Fallback: read directly from registry file
        if output_directory:
            client_type = self._lookup_client_from_file(batch_id, output_directory)
            if client_type:
                return client_type

        return None

    def _lookup_client_from_file(self, batch_id: str, output_directory: str) -> Optional[str]:
        """Look up client type directly from registry file.

        Args:
            batch_id: The batch job ID to look up
            output_directory: Directory containing the batch registry

        Returns:
            Client type string or None if not found
        """
        registry_file = Path(output_directory) / "batch" / ".batch_registry.json"
        if not registry_file.exists():
            return None

        try:
            with open(registry_file, "r", encoding="utf-8") as f:
                registry = json.load(f)

            # Search for batch_id in registry entries
            for entry in registry.values():
                if entry.get("batch_id") == batch_id:
                    return entry.get("provider")
        except (json.JSONDecodeError, OSError, KeyError):
            logger.debug("Failed to read batch registry file %s", registry_file, exc_info=True)

        return None
