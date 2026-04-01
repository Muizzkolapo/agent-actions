"""Core event infrastructure for centralized logging."""

# Lazy-load handlers (which pull in Rich) until actually needed.
# Events, manager, and protocols are lightweight and load on demand too.

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # events
    "BaseEvent": (".events", "BaseEvent"),
    "EventCategory": (".events", "EventCategory"),
    "EventLevel": (".events", "EventLevel"),
    "EventMeta": (".events", "EventMeta"),
    # handlers
    "ConsoleEventHandler": (".handlers", "ConsoleEventHandler"),
    "ContextDebugHandler": (".handlers", "ContextDebugHandler"),
    "JSONFileHandler": (".handlers", "JSONFileHandler"),
    # manager
    "EventManager": (".manager", "EventManager"),
    "fire_event": (".manager", "fire_event"),
    "get_manager": (".manager", "get_manager"),
    # protocols
    "CategoryFilter": (".protocols", "CategoryFilter"),
    "EventFilter": (".protocols", "EventFilter"),
    "EventHandler": (".protocols", "EventHandler"),
    "LevelFilter": (".protocols", "LevelFilter"),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        import importlib

        rel_module, attr = _LAZY_IMPORTS[name]
        mod = importlib.import_module(rel_module, __name__)
        val = getattr(mod, attr)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = list(_LAZY_IMPORTS.keys())
