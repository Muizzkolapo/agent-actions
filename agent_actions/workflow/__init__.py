"""Orchestration module for agent workflow execution.

Exports resolve lazily so that importing a leaf submodule (e.g.
``workflow.pipeline_file_mode``) does not execute the full coordinator
import chain, which would be circular for the processing modules it
reaches back into.
"""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_actions.workflow.coordinator import AgentWorkflow
    from agent_actions.workflow.models import (
        WorkflowPaths,
        WorkflowRuntimeConfig,
        WorkflowState,
    )
    from agent_actions.workflow.schema_service import WorkflowSchemaService

__all__ = [
    "AgentWorkflow",
    "WorkflowPaths",
    "WorkflowRuntimeConfig",
    "WorkflowState",
    "WorkflowSchemaService",
]

_EXPORTS = {
    "AgentWorkflow": "agent_actions.workflow.coordinator",
    "WorkflowPaths": "agent_actions.workflow.models",
    "WorkflowRuntimeConfig": "agent_actions.workflow.models",
    "WorkflowState": "agent_actions.workflow.models",
    "WorkflowSchemaService": "agent_actions.workflow.schema_service",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module_name), name)
