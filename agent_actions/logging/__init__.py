"""Agent Actions logging infrastructure."""

import importlib

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "LoggingConfig": (".config", "LoggingConfig"),
    "LogLevel": (".config", "LogLevel"),
    "BaseEvent": (".core", "BaseEvent"),
    "EventLevel": (".core", "EventLevel"),
    "EventManager": (".core", "EventManager"),
    "fire_event": (".core", "fire_event"),
    "get_manager": (".core", "get_manager"),
    "LoggerFactory": (".factory", "LoggerFactory"),
    "RedactingFilter": (".filters", "RedactingFilter"),
    "JSONFormatter": (".formatters", "JSONFormatter"),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        rel_module, attr = _LAZY_IMPORTS[name]
        mod = importlib.import_module(rel_module, __name__)
        val = getattr(mod, attr)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = list(_LAZY_IMPORTS.keys())
