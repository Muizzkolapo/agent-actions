"""Agent Actions framework entry point."""

import os

# The openai, anthropic and groq SDKs build their pydantic response models on first use
# unless this is false, and pydantic's rebuild is not thread-safe: records answered in
# one concurrent window parse their first responses together, and one can then fail with
# "BaseModel cannot be instantiated directly". Each SDK reads this once, as it is first
# imported, so it is set here, before any module of this package can import one.
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
