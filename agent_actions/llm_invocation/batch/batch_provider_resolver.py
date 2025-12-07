"""
Batch Provider Resolver.

Handles resolution and caching of batch providers based on configuration or batch ID.
Extracted from BatchService for better separation of concerns.
"""

from typing import Dict, Optional, Any

from agent_actions.llm_invocation.providers.base import BatchProvider
from agent_actions.llm_invocation.providers.factory import BatchProviderFactory
from agent_actions.errors import ConfigurationError, ConfigValidationError  # New modular pattern!


class BatchProviderResolver:
    """
    Resolves and caches batch providers.

    Handles provider instantiation from agent config or batch registry lookup.
    Maintains internal cache to avoid recreating providers.

    Example:
        resolver = BatchProviderResolver()
        provider = resolver.get_for_config(agent_config)
        provider2 = resolver.get_for_batch_id('batch_123', output_dir, registry_manager)
    """

    def __init__(self, provider_cache: Optional[Dict[str, BatchProvider]] = None, default_provider: Optional[BatchProvider] = None):
        """
        Initialize provider resolver.

        Args:
            provider_cache: Optional existing provider cache
            default_provider: Optional default provider to use as fallback
        """
        self._provider_cache = provider_cache if provider_cache is not None else {}
        self._default_provider = default_provider

    def get_for_config(self, agent_config: Dict[str, Any]) -> BatchProvider:
        """
        Get the appropriate provider based on agent configuration.

        Args:
            agent_config: Agent configuration dictionary (must be resolved via hierarchy)

        Returns:
            BatchProvider instance for the specified provider type

        Raises:
            ConfigurationError: If config is invalid or provider creation fails
        """
        required_fields = ['model_vendor', 'model_name', 'api_key']
        missing = [f for f in required_fields if not agent_config.get(f)]
        if missing:
            raise ConfigurationError(
                f"Batch service received incomplete config (missing: {', '.join(missing)})",
                context={
                    'missing_fields': missing,
                    'agent_type': agent_config.get('agent_type', 'unknown'),
                    'hint': 'Caller must resolve config hierarchy (project → workflow → action) before calling batch service'
                }
            )

        provider_type = agent_config.get('model_vendor')
        if not provider_type:
            raise ConfigValidationError(
                'model_vendor',
                "Missing required field 'model_vendor' for batch processing. Specify the LLM provider (e.g., openai, anthropic, gemini)."
            )

        provider_type = provider_type.lower()

        if provider_type == 'tool':
            raise ConfigurationError(
                "'tool' vendor does not support batch processing",
                context={
                    'provider_type': provider_type,
                    'supported_vendors': ['openai', 'gemini', 'anthropic']
                }
            )

        # Check cache
        if provider_type in self._provider_cache:
            return self._provider_cache[provider_type]

        # Create new provider
        try:
            provider_config = {}
            if provider_type == 'gemini' and agent_config.get('google_api_key'):
                provider_config['api_key'] = agent_config['google_api_key']
            elif provider_type == 'openai' and agent_config.get('openai_api_key'):
                provider_config['api_key'] = agent_config['openai_api_key']

            provider = BatchProviderFactory.create_provider(provider_type, provider_config)

            # Validate config
            is_valid, error_msg = provider.validate_config(agent_config)
            if not is_valid:
                raise ConfigurationError(
                    'Provider configuration validation failed',
                    context={'provider_type': provider_type, 'error_message': error_msg}
                )

            # Cache and return
            self._provider_cache[provider_type] = provider
            return provider

        except Exception as e:
            raise ConfigurationError(
                f'Failed to create provider for batch_provider_{provider_type}: {e}',
                context={'provider_type': provider_type},
                cause=e
            )

    def get_for_batch_id(self, batch_id: str, registry_manager, output_directory: Optional[str] = None) -> BatchProvider:
        """
        Get the provider that was used for a specific batch ID.

        Looks up the provider type from the batch registry and returns
        a provider instance (cached if available).

        Args:
            batch_id: The batch job ID
            registry_manager: BatchRegistryManager instance to lookup batch info
            output_directory: Output directory (for compatibility, can be None if registry_manager provided)

        Returns:
            BatchProvider instance

        Raises:
            ConfigurationError: If provider cannot be determined
        """
        if registry_manager:
            entry = registry_manager.get_batch_job_by_id(batch_id)

            if entry:
                provider_type = entry.provider

                # Check cache
                if provider_type in self._provider_cache:
                    return self._provider_cache[provider_type]
                else:
                    # Create new provider (will not be cached)
                    return BatchProviderFactory.create_provider(provider_type)

        # Fallback to default provider if available
        if self._default_provider:
            return self._default_provider

        raise ConfigurationError(
            f'Cannot determine provider for batch_id {batch_id}',
            context={'batch_id': batch_id, 'output_directory': output_directory}
        )
