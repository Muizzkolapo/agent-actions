"""
Compatibility shim for processor_helpers.

This module provides backward compatibility for imports that expect
'processor_helpers' when the actual file is 'utils_processor_helpers'.
"""

from .utils_processor_helpers import (
    apply_drops,
    run_dynamic_agent,
    transform_with_observe,
)

__all__ = ['apply_drops', 'run_dynamic_agent', 'transform_with_observe']
