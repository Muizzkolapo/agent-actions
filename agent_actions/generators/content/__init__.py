"""Content generators package - handles content generation logic."""

from importlib import import_module
from typing import Any

__all__ = ["ContentGenerator", "DataGenerator", "TargetGenerator"]

_module_map = {
    "ContentGenerator": ".content_generator",
    "DataGenerator": ".data_generator", 
    "TargetGenerator": ".target_generator"
}


def __getattr__(name: str) -> Any:  # pragma: no cover - thin wrapper
    if name in _module_map:
        module = import_module(f"{__name__}{_module_map[name]}")
        attr = getattr(module, name)
        globals()[name] = attr
        return attr
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

