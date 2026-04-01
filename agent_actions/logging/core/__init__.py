"""Core event infrastructure for centralized logging."""

import importlib

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "BaseEvent": (".events", "BaseEvent"),
    "EventCategory": (".events", "EventCategory"),
    "EventLevel": (".events", "EventLevel"),
    "EventMeta": (".events", "EventMeta"),
    "ConsoleEventHandler": (".handlers", "ConsoleEventHandler"),
    "ContextDebugHandler": (".handlers", "ContextDebugHandler"),
    "JSONFileHandler": (".handlers", "JSONFileHandler"),
    "EventManager": (".manager", "EventManager"),
    "fire_event": (".manager", "fire_event"),
    "get_manager": (".manager", "get_manager"),
    "CategoryFilter": (".protocols", "CategoryFilter"),
    "EventFilter": (".protocols", "EventFilter"),
    "EventHandler": (".protocols", "EventHandler"),
    "LevelFilter": (".protocols", "LevelFilter"),
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
