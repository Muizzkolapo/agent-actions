"""Core processing types and abstractions for unified record processing."""

import importlib

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "ProcessingContext": (".types", "ProcessingContext"),
    "ProcessingMode": (".types", "ProcessingMode"),
    "ProcessingResult": (".types", "ProcessingResult"),
    "ProcessingStatus": (".types", "ProcessingStatus"),
    "RetryState": (".types", "RetryState"),
    "GuardStatus": (".prepared_task", "GuardStatus"),
    "PreparedTask": (".prepared_task", "PreparedTask"),
    "PreparationContext": (".prepared_task", "PreparationContext"),
    "TaskPreparer": (".task_preparer", "TaskPreparer"),
    "get_task_preparer": (".task_preparer", "get_task_preparer"),
    "reset_task_preparer": (".task_preparer", "reset_task_preparer"),
    "BatchProvider": (".invocation", "BatchProvider"),
    "InvocationResult": (".invocation", "InvocationResult"),
    "InvocationStrategy": (".invocation", "InvocationStrategy"),
    "OnlineStrategy": (".invocation", "OnlineStrategy"),
    "BatchStrategy": (".invocation", "BatchStrategy"),
    "BatchSubmissionResult": (".invocation", "BatchSubmissionResult"),
    "InvocationStrategyFactory": (".invocation", "InvocationStrategyFactory"),
    "Enricher": (".enrichment", "Enricher"),
    "EnrichmentPipeline": (".enrichment", "EnrichmentPipeline"),
    "LineageEnricher": (".enrichment", "LineageEnricher"),
    "VersionIdEnricher": (".enrichment", "VersionIdEnricher"),
    "MetadataEnricher": (".enrichment", "MetadataEnricher"),
    "PassthroughEnricher": (".enrichment", "PassthroughEnricher"),
    "RequiredFieldsEnricher": (".enrichment", "RequiredFieldsEnricher"),
    "RecordProcessor": (".processor", "RecordProcessor"),
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
