"""
Factory for creating batch providers based on configuration.
"""

from typing import Optional, Dict, Any
import os

from .base import BatchProvider
from .openai.provider import OpenAIBatchProvider
from .gemini.provider import GeminiBatchProvider

# Import Anthropic provider with graceful fallback
try:
    from .anthropic.provider import AnthropicBatchProvider
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


class BatchProviderFactory:
    """
    Factory class for creating batch provider instances.
    
    This factory supports creating providers based on a provider type string,
    making it easy to switch between different batch processing backends.
    """
    
    @staticmethod
    def create_provider(provider_type: str = "openai", 
                       config: Optional[Dict[str, Any]] = None) -> BatchProvider:
        """
        Create a batch provider instance.
        
        Args:
            provider_type: Type of provider to create ("openai", "gemini", etc.)
            config: Optional configuration dict with provider-specific settings
            
        Returns:
            BatchProvider instance
            
        Raises:
            ValueError: If provider_type is not recognized
        """
        config = config or {}
        
        # Normalize provider type to lowercase
        provider_type = provider_type.lower()
        
        if provider_type == "openai":
            # Get API key from config or environment
            api_key = config.get("api_key") or os.getenv("OPENAI_API_KEY")
            return OpenAIBatchProvider(api_key=api_key)
            
        elif provider_type == "gemini":
            # Get API key from config or environment
            api_key = config.get("api_key") or os.getenv("GOOGLE_API_KEY")
            try:
                return GeminiBatchProvider(api_key=api_key)
            except ImportError as e:
                raise ValueError(f"Gemini provider not available: {e}")
            
        elif provider_type == "anthropic":
            if not ANTHROPIC_AVAILABLE:
                raise ValueError(
                    "Anthropic provider not available. Install with: pip install anthropic"
                )
            
            # Get API key from config or environment
            api_key = config.get("api_key") or os.getenv("CLAUDE_API_KEY")
            
            # Get Anthropic-specific config options
            anthropic_version = config.get("anthropic_version")
            enable_prompt_caching = config.get("enable_prompt_caching", False)
            
            try:
                return AnthropicBatchProvider(
                    api_key=api_key,
                    version=anthropic_version,
                    enable_prompt_caching=enable_prompt_caching
                )
            except ImportError as e:
                raise ValueError(f"Anthropic provider not available: {e}")
            
        else:
            supported_providers = ["openai", "gemini"]
            if ANTHROPIC_AVAILABLE:
                supported_providers.append("anthropic")
            
            raise ValueError(
                f"Unknown provider type: {provider_type}. "
                f"Supported providers: {', '.join(supported_providers)}"
            )
    
    @staticmethod
    def get_supported_providers() -> list[str]:
        """Get list of supported provider types."""
        providers = ["openai", "gemini"]
        if ANTHROPIC_AVAILABLE:
            providers.append("anthropic")
        return providers