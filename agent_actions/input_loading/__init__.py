"""
Compatibility module for core.loaders.data_loaders imports.

This module re-exports loaders from their new locations to maintain
backward compatibility after the repository restructuring.
"""

# Re-export from new locations within input_loading stage
from .extractors_source_data_loader import *
from .json_loader import *
from .xml_loader import *
from .tabular_loader import *
from .text_loader import *
from .base_base_loader import *
from agent_actions.llm_invocation.batch.loaders_batch_data_loader import *