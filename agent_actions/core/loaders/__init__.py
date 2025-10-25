"""
Compatibility module for core.loaders imports.

This module re-exports loaders from their new locations to maintain
backward compatibility after the repository restructuring.
"""

# Re-export from new locations in input_loading
from agent_actions.input_loading.extractors_source_data_loader import *
from agent_actions.input_loading.json_loader import *
from agent_actions.input_loading.xml_loader import *
from agent_actions.input_loading.tabular_loader import *
from agent_actions.input_loading.text_loader import *
from agent_actions.input_loading.base_base_loader import *
from agent_actions.llm_invocation.batch.loaders_batch_data_loader import *