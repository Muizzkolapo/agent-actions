"""Agent-actions event type definitions.

Canonical home for EventCategories and _safe_value_repr. All event
dataclasses live in their respective category modules (workflow_events,
batch_events, cache_events, etc.).

Event Code Prefixes:
    W - Workflow lifecycle events
    A - Action execution events
    B - Batch processing events
    L - LLM interaction events
    V - Validation events
    C - Cache events
    T - Template rendering events
    D - Data loading/parsing events
    G - Guard evaluation events
    R - Recovery/retry events
    F - Configuration loading events
    E - Environment variable events
    I - Initialization/CLI events
    P - Plugin/UDF discovery events
    RP - Record Processing Pipeline events
    BP - Batch Processing events (data processing)
    FIO - File I/O events
    DV - Data Validation events
    SO - Schema Operations events
    DT - Data Transformation events
    RC - Result Collection events
    CX - Context introspection events
"""

from typing import Any


class EventCategories:
    """Event category constants for agent-actions."""

    WORKFLOW = "workflow"
    ACTION = "action"
    BATCH = "batch"
    LLM = "llm"
    VALIDATION = "validation"
    CACHE = "cache"
    TEMPLATE = "template"
    DATA = "data"
    GUARD = "guard"
    RECOVERY = "recovery"
    CONFIGURATION = "configuration"
    ENVIRONMENT = "environment"
    INITIALIZATION = "initialization"
    PLUGIN = "plugin"
    DATA_PROCESSING = "data_processing"
    FILE_IO = "file_io"
    SCHEMA = "schema"
    TRANSFORMATION = "transformation"


def _safe_value_repr(value: Any, max_length: int = 100) -> str:
    """Safely convert a value to a truncated string for logging."""
    if value is None:
        return ""
    try:
        if isinstance(value, (str, int, float, bool)):
            result = str(value)
        else:
            result = repr(value)
        if len(result) > max_length:
            return result[: max_length - 3] + "..."
        return result
    except Exception:
        return "<unserializable>"
