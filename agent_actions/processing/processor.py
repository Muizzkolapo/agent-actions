"""Thin re-export shim for RecordProcessor.

All production code should import from this module.
The implementation lives in record_processor.py.
"""

from .record_processor import RecordProcessor, _is_empty_output

__all__ = ["RecordProcessor", "_is_empty_output"]
