"""Agent Actions framework entry point."""

import os

# The SDKs otherwise build their pydantic models on first use, which is not thread-safe
# across a record_concurrency window. Each reads this once, as it is first imported.
os.environ.setdefault("DEFER_PYDANTIC_BUILD", "false")

from agent_actions.__version__ import __version__  # noqa: E402
from agent_actions.expectations.registry import expectation_check  # noqa: E402
from agent_actions.utils.udf_management.registry import FileUDFResult, udf_tool  # noqa: E402

__all__ = [
    "__version__",
    "udf_tool",
    "FileUDFResult",
    "expectation_check",
]
