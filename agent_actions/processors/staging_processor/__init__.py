"""Staging processor package initialization."""

from importlib import import_module
from typing import Any

__all__ = ["StagingContentLoader", "generate_staging", "StagingProcessor"]

_module_map = {
    "StagingContentLoader": ".staging_content",
    "generate_staging": ".staging_loader",
    "StagingProcessor": ".staging_processor",
}


def __getattr__(name: str) -> Any:  # pragma: no cover - thin wrapper
    if name in _module_map:
        module = import_module(f"{__name__}{_module_map[name]}")
        attr = getattr(module, name)
        globals()[name] = attr
        return attr
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

