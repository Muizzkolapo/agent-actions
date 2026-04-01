"""Core processing types and abstractions for unified record processing."""

# Lazy-load all symbols to avoid pulling in config.schema (Pydantic), logging
# (Rich), and pyparsing on first import. Consumers that do
# `from agent_actions.processing import RecordProcessor` still work — the
# import just happens on first access instead of at module load time.

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # types
    "ProcessingContext": (".types", "ProcessingContext"),
    "ProcessingMode": (".types", "ProcessingMode"),
    "ProcessingResult": (".types", "ProcessingResult"),
    "ProcessingStatus": (".types", "ProcessingStatus"),
    "RetryState": (".types", "RetryState"),
    # prepared_task
    "GuardStatus": (".prepared_task", "GuardStatus"),
    "PreparedTask": (".prepared_task", "PreparedTask"),
    "PreparationContext": (".prepared_task", "PreparationContext"),
    # task_preparer
    "TaskPreparer": (".task_preparer", "TaskPreparer"),
    "get_task_preparer": (".task_preparer", "get_task_preparer"),
    "reset_task_preparer": (".task_preparer", "reset_task_preparer"),
    # invocation
    "BatchProvider": (".invocation", "BatchProvider"),
    "InvocationResult": (".invocation", "InvocationResult"),
    "InvocationStrategy": (".invocation", "InvocationStrategy"),
    "OnlineStrategy": (".invocation", "OnlineStrategy"),
    "BatchStrategy": (".invocation", "BatchStrategy"),
    "BatchSubmissionResult": (".invocation", "BatchSubmissionResult"),
    "InvocationStrategyFactory": (".invocation", "InvocationStrategyFactory"),
    # enrichment
    "Enricher": (".enrichment", "Enricher"),
    "EnrichmentPipeline": (".enrichment", "EnrichmentPipeline"),
    "LineageEnricher": (".enrichment", "LineageEnricher"),
    "VersionIdEnricher": (".enrichment", "VersionIdEnricher"),
    "MetadataEnricher": (".enrichment", "MetadataEnricher"),
    "PassthroughEnricher": (".enrichment", "PassthroughEnricher"),
    "RequiredFieldsEnricher": (".enrichment", "RequiredFieldsEnricher"),
    # processor
    "RecordProcessor": (".processor", "RecordProcessor"),
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
