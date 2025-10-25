"""
Compatibility shim for processor_utils.

This module provides backward compatibility for imports that expect
'processor_utils' when the actual file is 'utils_processor_utils'.
"""

from .utils_processor_utils import ProcessorUtils

__all__ = ['ProcessorUtils']
