"""
Compatibility module for core.loaders.data_loaders imports.

This module re-exports loaders from their new locations to maintain
backward compatibility after the repository restructuring.
"""

from agent_actions.orchestration.dependency_injection import registry as _registry

# Re-export from new locations
from agent_actions.llm_invocation.batch.infrastructure.batch_data_loader import *
from .base_base_loader import *
from .extractors_source_data_loader import *
from .json_loader import *
from .tabular_loader import *
from .text_loader import *
from .xml_loader import *

# Register loaders after imports to avoid circular dependencies
_registry.register_loader("source_data")(SourceDataLoader)
