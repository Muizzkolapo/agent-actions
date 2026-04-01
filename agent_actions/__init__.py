"""Agent Actions framework entry point."""

import importlib

from agent_actions.__version__ import __version__
from agent_actions.utils.udf_management.registry import FileUDFResult, udf_tool

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "reprompt_validation": ("agent_actions.processing.recovery.validation", "reprompt_validation"),
    "get_validation_function": ("agent_actions.processing.recovery.validation", "get_validation_function"),
    "list_validation_functions": ("agent_actions.processing.recovery.validation", "list_validation_functions"),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr = _LAZY_IMPORTS[name]
        mod = importlib.import_module(module_path)
        val = getattr(mod, attr)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "__version__",
    "udf_tool",
    "FileUDFResult",
    *_LAZY_IMPORTS,
]
