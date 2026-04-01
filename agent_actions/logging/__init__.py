"""Agent Actions logging infrastructure."""

# Lazy-load to avoid pulling in Rich (~55ms) and event classes (~30ms)
# on package import. The logging subsystem is only needed when a workflow
# actually runs, not when the user imports `agent_actions` or `udf_tool`.

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # config
    "LoggingConfig": (".config", "LoggingConfig"),
    "LogLevel": (".config", "LogLevel"),
    # core
    "BaseEvent": (".core", "BaseEvent"),
    "EventLevel": (".core", "EventLevel"),
    "EventManager": (".core", "EventManager"),
    "fire_event": (".core", "fire_event"),
    "get_manager": (".core", "get_manager"),
    # factory
    "LoggerFactory": (".factory", "LoggerFactory"),
    # filters
    "RedactingFilter": (".filters", "RedactingFilter"),
    # formatters
    "JSONFormatter": (".formatters", "JSONFormatter"),
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
