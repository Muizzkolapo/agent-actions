"""Agent Actions framework entry point."""

import importlib
import importlib.util
import os
from typing import TYPE_CHECKING, Any

# The SDKs otherwise build their pydantic models on first use, which is not thread-safe
# across a record_concurrency window. Each reads this once, as it is first imported.
os.environ.setdefault("DEFER_PYDANTIC_BUILD", "false")

from agent_actions.__version__ import __version__  # noqa: E402

if TYPE_CHECKING:
    from agent_actions.expectations.registry import expectation_check
    from agent_actions.utils.udf_management.registry import FileUDFResult, udf_tool

__all__ = [
    "__version__",
    "udf_tool",
    "FileUDFResult",
    "expectation_check",
]

# Resolved on first access so importing the package does not load the expectation
# checks (and the LLM judge behind them) until something asks for them.
_LAZY_EXPORTS = {
    "expectation_check": "agent_actions.expectations.registry",
    "udf_tool": "agent_actions.utils.udf_management.registry",
    "FileUDFResult": "agent_actions.utils.udf_management.registry",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is not None:
        value = getattr(importlib.import_module(module_name), name)
    elif not name.startswith("_") and importlib.util.find_spec(f"{__name__}.{name}"):
        # Subpackages stay reachable as attributes after a bare ``import agent_actions``,
        # as they were when the eager imports above loaded them as a side effect.
        value = importlib.import_module(f"{__name__}.{name}")
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
