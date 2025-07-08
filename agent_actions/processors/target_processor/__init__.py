"""Target processor package initialization."""

from importlib import import_module
from typing import Any

__all__ = [
    "DataGenerator",
    "DataProcessor",
    "OutputHandler",
    "TargetGenerator",
    "TargetContentProcessor",
]

_module_map = {
    "DataGenerator": ".data_generator",
    "DataProcessor": ".data_processor",
    "OutputHandler": ".output_handler",
    "TargetGenerator": ".target_generator",
    "TargetContentProcessor": ".target_content_processor",
}


def __getattr__(name: str) -> Any:  # pragma: no cover - thin wrapper
    if name in _module_map:
        module = import_module(f"{__name__}{_module_map[name]}")
        attr = getattr(module, name)
        globals()[name] = attr
        return attr
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

