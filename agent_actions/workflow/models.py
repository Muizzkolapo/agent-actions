"""Dataclass models for action workflow orchestration."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_actions.config.path_config import resolve_project_root as _resolve_project_root


@dataclass
class WorkflowPaths:
    """Path configuration for workflow."""

    constructor_path: str
    user_code_path: str | None
    default_path: str
    parent_output: str | None = None
    parent_source: str | None = None
    parent_pipeline: str | None = None


@dataclass
class WorkflowRuntimeConfig:
    """Runtime execution context for workflow initialization.

    This is NOT the user-facing config schema (see ``WorkflowConfig`` in
    ``agent_actions.config.schema`` for that).  This dataclass holds paths,
    feature flags, and a ``ConfigManager`` reference needed by the workflow
    engine at execution time.
    """

    paths: WorkflowPaths
    use_tools: bool
    run_upstream: bool = False
    run_downstream: bool = False
    fresh: bool = False
    verify_keys: bool = False
    manager: Any = None  # ConfigManager instance
    project_root: Path | None = None

    def resolve_project_root(self) -> Path:
        """Resolve effective project root from manager, config, or cwd."""
        explicit = (self.manager.project_root if self.manager else None) or self.project_root
        return _resolve_project_root(explicit)


@dataclass
class WorkflowState:
    """Runtime state for workflow execution."""

    previous_action_type: str | None = None
    failed: bool = False


@dataclass
class RuntimeContext:
    """Runtime context for workflow execution."""

    state: WorkflowState
    console: Any  # Rich Console


@dataclass
class CompiledAction:
    """Metadata for an action in a compiled multi-workflow DAG."""

    name: str  # Qualified: "workflow_name::action_name"
    local_name: str  # Original action name within source workflow
    source_workflow: str  # Name of the workflow this action came from
    source_workflow_dir: Path  # Path to source workflow directory (for agent_io)
    source_data_source: Any = None  # data_source config from source workflow defaults


@dataclass
class CompilationResult:
    """Output of WorkflowCompiler.compile()."""

    merged_actions: list[dict[str, Any]]  # Pre-Pydantic, dict deps rewritten to strings
    action_metadata: dict[str, CompiledAction]  # Keyed by qualified name
    primary_workflow: str  # The workflow the user invoked
    involved_workflows: list[str]  # All workflows in the compiled DAG
    workflow_graph: dict[str, list[str]]  # Workflow-level dep graph


@dataclass
class WorkflowMetadata:
    """Workflow configuration metadata."""

    agent_name: str
    execution_order: list[str]
    action_indices: dict[str, int]
    action_configs: dict[str, dict[str, Any]]
    child_pipeline: str | None = None
    compilation: CompilationResult | None = None


@dataclass
class ActionLogParams:
    """Parameters for logging action results."""

    idx: int
    action_name: str
    total_actions: int
    result: Any
    end_time: datetime
    duration: float
    run_mode: str = ""


@dataclass
class CoreServices:
    """Core execution services."""

    action_runner: Any
    state_manager: Any
    action_executor: Any
    action_level_orchestrator: Any


@dataclass
class SupportServices:
    """Supporting services for workflow execution."""

    version_correlator: Any
    skip_evaluator: Any
    batch_manager: Any
    output_manager: Any
    manifest_manager: Any = None


@dataclass
class WorkflowServices:
    """Container for workflow orchestration services."""

    core: CoreServices
    support: SupportServices


# Backward-compatible alias
AgentLogParams = ActionLogParams
