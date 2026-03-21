"""Thin re-export shim: RecordProcessor and BatchProcessor.

All production code should import from this module to preserve backward
compatibility. The implementations live in record_processor.py and
batch_processor.py respectively.
"""

from .batch_processor import BatchProcessor
from .record_processor import RecordProcessor, _is_empty_output

__all__ = ["RecordProcessor", "BatchProcessor", "_is_empty_output"]
