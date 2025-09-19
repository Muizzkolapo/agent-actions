"""
Compatibility module for core.loaders imports.

This module re-exports loaders from their new locations to maintain
backward compatibility after the repository restructuring.
"""

# Re-export from new locations
from ...agents.extractors.source_data_loader import *
from ...agents.extractors.json_loader import *
from ...agents.extractors.xml_loader import *
from ...agents.extractors.tabular_loader import *
from ...agents.extractors.text_loader import *
from ...agents.base.base_loader import *
from ...integrations.loaders.batch_data_loader import *