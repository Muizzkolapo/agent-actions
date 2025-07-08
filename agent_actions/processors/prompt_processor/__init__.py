"""Prompt processor package initialization."""

from importlib import import_module
from typing import Any

__all__ = [
    "ContextPreprocessor",
    "PromptFormatter",
    "ResponseTransformer",
    "SampleEnricher",
    "PromptUtils",
]

_module_map = {
    "ContextPreprocessor": ".context_preprocessor",
    "PromptFormatter": ".prompt_formatter",
    "ResponseTransformer": ".response_transformer",
    "SampleEnricher": ".sample_enricher",
    "PromptUtils": ".prompt_utils",
}


def __getattr__(name: str) -> Any:  # pragma: no cover - thin wrapper
    if name in _module_map:
        module = import_module(f"{__name__}{_module_map[name]}")
        attr = getattr(module, name)
        globals()[name] = attr
        return attr
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

