"""UDF registration and execution system."""

import importlib

from .registry import (
    FileUDFResult,
    clear_registry,
    get_udf,
    get_udf_metadata,
    list_udfs,
    udf_tool,
)

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "load_user_defined_function": (".tooling", "load_user_defined_function"),
    "execute_user_defined_function": (".tooling", "execute_user_defined_function"),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        rel_module, attr = _LAZY_IMPORTS[name]
        mod = importlib.import_module(rel_module, __name__)
        val = getattr(mod, attr)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "udf_tool",
    "get_udf",
    "get_udf_metadata",
    "list_udfs",
    "clear_registry",
    "FileUDFResult",
    *_LAZY_IMPORTS,
]
