"""Thin compatibility shim re-exporting the static analyzer implementation."""

from agent_actions.validation.static_analyzer import (
    WorkflowStaticAnalyzer,
    analyze_workflow,
)

__all__ = [
    "WorkflowStaticAnalyzer",
    "analyze_workflow",
]
