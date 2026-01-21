"""Groq client module."""
# pyright: reportImportCycles=false

from .client import GroqClient

try:
    from .batch_client import GroqBatchClient

    __all__ = ["GroqClient", "GroqBatchClient"]
except ImportError:
    __all__ = ["GroqClient"]
