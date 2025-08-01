"""
Factory for creating batch providers based on configuration.
"""

from typing import Optional, Dict, Any
import os

from .base import BatchProvider
from .openai_provider import OpenAIBatchProvider
from .gemini_provider import GeminiBatchProvider


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
            
        else:
            raise ValueError(
                f"Unknown provider type: {provider_type}. "
                f"Supported providers: openai, gemini"
            )
    
    @staticmethod
    def get_supported_providers() -> list[str]:
        """Get list of supported provider types."""
        return ["openai", "gemini"]