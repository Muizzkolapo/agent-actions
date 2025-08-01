# Provider interfaces and implementations for batch processing

from .base import BatchProvider, BatchTask, BatchResult

# Import providers with graceful error handling for missing dependencies
_available_providers = ['BatchProvider', 'BatchTask', 'BatchResult']

try:
    from .openai_provider import OpenAIBatchProvider
    _available_providers.append('OpenAIBatchProvider')
except ImportError:
    pass

try:
    from .gemini_provider import GeminiBatchProvider
    _available_providers.append('GeminiBatchProvider')
except ImportError:
    pass

try:
    from .anthropic_provider import AnthropicBatchProvider
    _available_providers.append('AnthropicBatchProvider')
except ImportError:
    pass

__all__ = _available_providers