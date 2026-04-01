"""UDF registration and execution system."""

from .registry import (
    FileUDFResult,
    clear_registry,
    get_udf,
    get_udf_metadata,
    list_udfs,
    udf_tool,
)

# Lazy-load tooling to avoid pulling in the full config chain at import time.
# execute_user_defined_function and load_user_defined_function are only needed
# when actually running a workflow, not when a user's tools/*.py imports udf_tool.

_LAZY = {
    "load_user_defined_function": ".tooling",
    "execute_user_defined_function": ".tooling",
}


def __getattr__(name: str):
    if name in _LAZY:
        import importlib

        mod = importlib.import_module(_LAZY[name], __name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "udf_tool",
    "get_udf",
    "get_udf_metadata",
    "list_udfs",
    "clear_registry",
    "load_user_defined_function",
    "execute_user_defined_function",
    "FileUDFResult",
]
