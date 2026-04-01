"""Agent Actions framework entry point."""

from agent_actions.__version__ import __version__
from agent_actions.utils.udf_management.registry import FileUDFResult, udf_tool


def __getattr__(name: str):
    """Lazy-load heavy symbols to avoid importing the full processing chain on startup."""
    _lazy = {
        "reprompt_validation": "agent_actions.processing.recovery.validation",
        "get_validation_function": "agent_actions.processing.recovery.validation",
        "list_validation_functions": "agent_actions.processing.recovery.validation",
    }
    if name in _lazy:
        import importlib

        mod = importlib.import_module(_lazy[name])
        val = getattr(mod, name)
        globals()[name] = val  # cache for subsequent access
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "__version__",
    "udf_tool",
    "FileUDFResult",
    "reprompt_validation",
    "get_validation_function",
    "list_validation_functions",
]
