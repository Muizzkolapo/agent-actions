"""Compatibility shim for base_loader."""

# pylint: disable=unused-import
# These imports are intentionally re-exported for backward compatibility
from agent_actions.input_loading.base_base_loader import (
    BaseLoader,
    IDataLoader,
    ProcessingMode,
    T,
    logger,
    retry,
)
