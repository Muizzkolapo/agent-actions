"""
Compatibility shim for processor_helpers.

This module provides backward compatibility for imports that expect
'processor_helpers' when the actual file is 'utils_processor_helpers'.
"""

from .utils_processor_helpers import (
    run_dynamic_agent,
    transform_with_passthrough,
)

__all__ = ['run_dynamic_agent', 'transform_with_passthrough']
