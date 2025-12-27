"""Mistral client module."""

from .client import MistralClient

try:
    from .batch_client import MistralBatchClient

    __all__ = ["MistralClient", "MistralBatchClient"]
except ImportError:
    __all__ = ["MistralClient"]
