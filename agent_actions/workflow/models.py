"""
Dataclass models for agent workflow orchestration.

This module contains the data structures used by AgentWorkflow for
configuration, state management, and service organization.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Any


@dataclass
class WorkflowPaths:
    """Path configuration for workflow."""

    constructor_path: str
    user_code_path: Optional[str]
    default_path: str
    parent_output: Optional[str] = None
    parent_source: Optional[str] = None
    parent_pipeline: Optional[str] = None


@dataclass
class WorkflowConfig:
    """Configuration container for workflow initialization."""

    paths: WorkflowPaths
    use_tools: bool
    run_upstream: bool = False
    run_downstream: bool = False
    manager: Any = None  # ConfigManager instance


@dataclass
class WorkflowState:
    """Runtime state for workflow execution."""

    previous_agent_type: Optional[str] = None
    ephemeral_directories: list = None
    failed: bool = False

    def __post_init__(self):
        """Initialize mutable defaults."""
        if self.ephemeral_directories is None:
            self.ephemeral_directories = []


@dataclass
class RuntimeContext:
    """Runtime context for workflow execution."""

    state: WorkflowState
    console: Any  # Rich Console


@dataclass
class WorkflowMetadata:
    """Workflow configuration metadata."""

    agent_name: str
    execution_order: list
    agent_indices: dict
    agent_configs: dict
    child_pipeline: Optional[str] = None


@dataclass
class AgentLogParams:
    """Parameters for logging agent results."""

    idx: int
    agent_name: str
    total_agents: int
    result: Any
    end_time: datetime
    duration: float


@dataclass
class CoreServices:
    """Core execution services."""

    agent_runner: Any
    state_manager: Any
    agent_executor: Any
    action_level_orchestrator: Any


@dataclass
class SupportServices:
    """Supporting services for workflow execution."""

    batch_service: Any
    loop_correlator: Any
    skip_evaluator: Any
    batch_manager: Any
    output_manager: Any
    manifest_manager: Any = None


@dataclass
class WorkflowServices:
    """Container for workflow orchestration services."""

    core: CoreServices
    support: SupportServices
