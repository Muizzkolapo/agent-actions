"""
Compatibility module for core.loaders.data_loaders imports.

This module re-exports loaders from their new locations to maintain
backward compatibility after the repository restructuring.
"""

from agent_actions.config.di.container import registry as _registry

# Re-export from new locations
from agent_actions.llm.batch.infrastructure.batch_data_loader import *
from .base import *
from .source_data import *
from .json import *
from .tabular import *
from .text import *
from .xml import *

# Register loaders after imports to avoid circular dependencies
_registry.register_loader("source_data")(SourceDataLoader)
