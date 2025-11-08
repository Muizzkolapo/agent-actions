"""Workflow configuration schema definitions."""

from .new_format_schema import (
    ActionKind,
    Granularity,
    LoopConfig,
    ActionConfig,
    DefaultsConfig,
    WorkflowConfigV2
)

__all__ = [
    "ActionKind",
    "Granularity",
    "LoopConfig",
    "ActionConfig",
    "DefaultsConfig",
    "WorkflowConfigV2"
]