"""
Compatibility module for core.loaders.data_loaders imports.

This module re-exports loaders from their new locations to maintain
backward compatibility after the repository restructuring.
"""

from agent_actions.config.di.container import registry as _registry

# Re-export from new locations
from agent_actions.llm.batch.infrastructure.batch_data_loader import BatchDataLoader
from .base import BaseLoader, retry
from .source_data import SourceDataLoader
from .json import JsonLoader
from .tabular import TabularLoader
from .text import TextLoader
from .xml import XmlLoader

__all__ = [
    "BatchDataLoader",
    "BaseLoader",
    "retry",
    "SourceDataLoader",
    "JsonLoader",
    "TabularLoader",
    "TextLoader",
    "XmlLoader",
]

# Register loaders after imports to avoid circular dependencies
_registry.register_loader("source_data")(SourceDataLoader)
