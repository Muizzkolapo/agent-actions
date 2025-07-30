"""Loaders module initialization."""

from importlib import import_module
from typing import Any

__all__ = [
    "BaseLoader",
    "BatchDataLoader",
    "TextLoader",
    "JsonLoader",
    "TabularLoader",
    "XmlLoader",
]

_module_map = {
    "BaseLoader": ".base_loader",
    "BatchDataLoader": ".batch_data_loader",
    "TextLoader": ".text_loader",
    "JsonLoader": ".json_loader",
    "TabularLoader": ".tabular_loader",
    "XmlLoader": ".xml_loader",
}


def __getattr__(name: str) -> Any:  # pragma: no cover - thin wrapper
    if name in _module_map:
        module = import_module(f"{__name__}{_module_map[name]}")
        attr = getattr(module, name)
        globals()[name] = attr
        return attr
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

