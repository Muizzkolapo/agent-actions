"""Resolves and caches batch clients based on configuration or batch ID."""

import hashlib
import logging
from typing import Any

from pydantic import SecretStr

logger = logging.getLogger(__name__)

from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.batch_base import BaseBatchClient
from agent_actions.llm.providers.batch_client_factory import BatchClientFactory
from agent_actions.llm.providers.client_base import BaseClient
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.cache_events import CacheHitEvent, CacheMissEvent
from agent_actions.utils.constants import API_KEY_KEY


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
                    "agent_type": agent_config.get("agent_type") or "NOT_SET",
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
                    "supported_clients": BatchClientFactory.get_supported_clients(),
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
            client_config: dict[str, Any] = {}
            if agent_config.get(API_KEY_KEY):
                client_config["api_key"] = BaseClient.get_api_key(agent_config)
            if agent_config.get("base_url"):
                client_config["base_url"] = agent_config["base_url"]
            if agent_config.get("batch_max_workers") is not None:
                client_config["batch_max_workers"] = agent_config["batch_max_workers"]

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
        except ImportError as e:
            raise ConfigurationError(
                f"Provider SDK not installed for '{client_type}'",
                context={
                    "client_type": client_type,
                    "hint": f"Install the provider package: pip install agent-actions[{client_type}]",
                },
                cause=e,
            ) from e
        except KeyError as e:
            raise ConfigurationError(
                f"Missing required configuration key: {e}",
                context={"client_type": client_type},
                cause=e,
            ) from e
        except OSError as e:
            raise ConfigurationError(
                f"Infrastructure error creating client for '{client_type}': {e}",
                context={"client_type": client_type, "error_type": type(e).__name__},
                cause=e,
            ) from e
        except (TypeError, ValueError) as e:
            raise ConfigurationError(
                f"Invalid configuration for '{client_type}': {e}",
                context={"client_type": client_type},
                cause=e,
            ) from e

    def get_for_batch_id(
        self,
        batch_id: str,
        registry_manager,
        output_directory: str | None = None,
        agent_config: dict[str, Any] | None = None,
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
            agent_config: Optional agent config for API key resolution on
                cache miss (avoids falling back to hardcoded env var names)

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
            config = self._resolve_api_key_config(client_type, agent_config)
            return BatchClientFactory.create_client(client_type, config)

        if self._default_client:
            return self._default_client

        raise ConfigurationError(
            f"Cannot determine client for batch_id {batch_id}",
            context={"batch_id": batch_id, "output_directory": output_directory},
        )

    @staticmethod
    def _resolve_api_key_config(vendor: str, agent_config: dict[str, Any] | None) -> dict[str, Any]:
        """Build a config dict with the API key for creating a batch client.

        Resolution order:
        1. agent_config["api_key"] → resolve env var (same path online mode uses)
        2. Vendor config class default env var name (e.g. ANTHROPIC_API_KEY)
        3. Empty dict → factory raises ConfigurationError (no silent fallback)

        Raises:
            ConfigurationError: If key resolution fails for non-config reasons
                (ImportError, KeyError, OSError). Only ConfigurationError from
                get_api_key (env var not set) triggers fallback to step 2.
        """
        import os

        # 1. Try agent_config (user's actual configured key name)
        if agent_config and agent_config.get(API_KEY_KEY):
            try:
                key = BaseClient.get_api_key(agent_config)
                if key:
                    return {"api_key": key}
            except ConfigurationError:
                logger.debug(
                    "API key from agent_config not resolvable for vendor '%s', "
                    "falling back to vendor default env var",
                    vendor,
                    exc_info=True,
                )
            except ImportError as e:
                raise ConfigurationError(
                    f"Provider SDK not installed for vendor '{vendor}'",
                    context={
                        "vendor": vendor,
                        "hint": f"Install the provider package: pip install agent-actions[{vendor}]",
                    },
                    cause=e,
                ) from e
            except KeyError as e:
                raise ConfigurationError(
                    f"Missing required config key during API key resolution: {e}",
                    context={"vendor": vendor, "missing_key": str(e)},
                    cause=e,
                ) from e
            except OSError as e:
                raise ConfigurationError(
                    f"Infrastructure error during API key resolution for vendor '{vendor}': {e}",
                    context={"vendor": vendor, "error_type": type(e).__name__},
                    cause=e,
                ) from e

        # 2. Try vendor config class default
        from agent_actions.validation.preflight.resolution_service import (
            _get_api_key_env_name,
        )

        env_name = _get_api_key_env_name(vendor)
        if env_name:
            key = os.environ.get(env_name)
            if key:
                return {"api_key": key}

        return {}

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
        _raw = agent_config.get(API_KEY_KEY) or ""
        api_key = _raw.get_secret_value() if isinstance(_raw, SecretStr) else _raw
        base_url = agent_config.get("base_url") or ""
        discriminator = f"{api_key}|{base_url}"
        if api_key or base_url:
            key_hash = hashlib.sha256(discriminator.encode()).hexdigest()[:12]
            return f"{client_type}:{key_hash}"
        return client_type

    def _resolve_client_type(
        self, batch_id: str, registry_manager, output_directory: str | None
    ) -> str | None:
        if registry_manager:
            entry = registry_manager.get_batch_job_by_id(batch_id)
            if entry:
                return entry.provider  # type: ignore[no-any-return]
        return None
