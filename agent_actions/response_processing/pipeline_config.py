"""Pipeline configuration models for workflow and stage management."""

from enum import Enum
from typing import Dict, Any, Optional, List, Literal

from pydantic import BaseModel, Field, field_validator
from agent_actions.errors import ConfigValidationError, WorkflowError


class ExecutionMode(str, Enum):
    """Pipeline execution modes."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    MIXED = "mixed"


class ErrorHandlingStrategy(str, Enum):
    """Error handling strategies for pipeline execution."""

    FAIL_FAST = "fail_fast"
    SKIP_ERRORS = "skip_errors"
    COLLECT_ERRORS = "collect_errors"
    RETRY_FAILED = "retry_failed"


class StageType(str, Enum):
    """Types of pipeline stages."""

    VALIDATION = "validation"
    TRANSFORMATION = "transformation"
    ENRICHMENT = "enrichment"
    NORMALIZATION = "normalization"
    FILTERING = "filtering"
    AGGREGATION = "aggregation"
    CUSTOM = "custom"


class StageConfig(BaseModel):
    """Configuration for a pipeline stage."""

    name: str = Field(..., description="Unique stage name")
    stage_type: StageType = Field(..., description="Type of stage")
    description: str = Field(default="", description="Stage description")
    enabled: bool = Field(default=True, description="Whether stage is enabled")
    timeout: Optional[int] = Field(default=None, ge=1, description="Stage timeout in seconds")
    retry_attempts: int = Field(default=0, ge=0, description="Number of retry attempts")
    retry_delay: float = Field(default=1.0, ge=0.0, description="Delay between retries")
    depends_on: List[str] = Field(default_factory=list, description="Stages this stage depends on")
    run_condition: Optional[str] = Field(
        default=None, description="Condition for running this stage"
    )
    config: Dict[str, Any] = Field(default_factory=dict, description="Stage-specific configuration")
    validate_input: bool = Field(default=True, description="Validate input data")
    validate_output: bool = Field(default=True, description="Validate output data")
    input_schema: Optional[Dict[str, Any]] = Field(
        default=None, description="Input validation schema"
    )
    output_schema: Optional[Dict[str, Any]] = Field(
        default=None, description="Output validation schema"
    )


class AgentStageConfig(StageConfig):
    """Configuration for agent-based pipeline stages."""

    stage_type: Literal[StageType.CUSTOM] = StageType.CUSTOM
    agent_name: str = Field(..., description="Name of the agent to execute")
    agent_config: Dict[str, Any] = Field(default_factory=dict, description="Agent configuration")
    few_shot: int = Field(default=0, ge=0, description="Number of few-shot samples")
    parallel_execution: bool = Field(default=False, description="Execute agent in parallel")
    batch_size: Optional[int] = Field(
        default=None, ge=1, description="Batch size for agent execution"
    )


class WorkflowConfig(BaseModel):
    """Configuration for agent workflow execution."""

    name: str = Field(..., description="Workflow name")
    description: str = Field(default="", description="Workflow description")
    version: str = Field(default="1.0.0", description="Workflow version")
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.SEQUENTIAL, description="Execution mode"
    )
    error_handling: ErrorHandlingStrategy = Field(
        default=ErrorHandlingStrategy.COLLECT_ERRORS, description="Error handling strategy"
    )
    max_concurrency: int = Field(default=5, ge=1, description="Maximum concurrent executions")
    global_timeout: Optional[int] = Field(default=None, ge=1, description="Global workflow timeout")
    agents: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict, description="Agent configurations"
    )
    execution_order: List[str] = Field(default_factory=list, description="Agent execution order")
    output_config: Dict[str, Any] = Field(default_factory=dict, description="Output configuration")
    artifact_config: Dict[str, Any] = Field(
        default_factory=dict, description="Artifact configuration"
    )
    global_filters: List[str] = Field(default_factory=list, description="Global filter conditions")
    where_clauses: Dict[str, Any] = Field(
        default_factory=dict, description="WHERE clause configurations"
    )

    @field_validator("execution_order")
    @classmethod
    def validate_execution_order(cls, v, info):
        """Validate that all agents in execution order are defined."""
        if "agents" in info.data:
            agents = info.data["agents"]
            undefined_agents = [agent for agent in v if agent not in agents]
            if undefined_agents:
                raise ConfigValidationError(
                    "execution_order",
                    f"Agents in execution_order not defined: {undefined_agents}",
                    context={
                        "undefined_agents": undefined_agents,
                        "execution_order": v,
                        "defined_agents": list(agents.keys()),
                        "operation": "validate_workflow",
                    },
                )
        return v


class PipelineConfig(BaseModel):
    """Main pipeline configuration."""

    name: str = Field(..., description="Pipeline name")
    description: str = Field(default="", description="Pipeline description")
    version: str = Field(default="1.0.0", description="Pipeline version")
    execution_mode: ExecutionMode = Field(default=ExecutionMode.SEQUENTIAL)
    error_handling: ErrorHandlingStrategy = Field(default=ErrorHandlingStrategy.COLLECT_ERRORS)
    max_parallel_stages: int = Field(default=5, ge=1, description="Maximum parallel stages")
    pipeline_timeout: Optional[int] = Field(
        default=None, ge=1, description="Pipeline timeout in seconds"
    )
    stages: List[StageConfig] = Field(default_factory=list, description="Pipeline stages")
    stage_registry: Dict[str, StageConfig] = Field(
        default_factory=dict, description="Registered stages"
    )
    enable_monitoring: bool = Field(default=True, description="Enable pipeline monitoring")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    metrics_enabled: bool = Field(default=True, description="Enable metrics collection")
    pre_pipeline_hooks: List[str] = Field(default_factory=list, description="Pre-pipeline hooks")
    post_pipeline_hooks: List[str] = Field(default_factory=list, description="Post-pipeline hooks")
    stage_interceptors: Dict[str, List[str]] = Field(
        default_factory=dict, description="Stage interceptors"
    )

    def add_stage(self, stage: StageConfig) -> "PipelineConfig":
        """Add a stage to the pipeline."""
        if stage.name in [s.name for s in self.stages]:
            raise ConfigValidationError(
                "stage_name",
                f"Stage '{stage.name}' already exists",
                context={
                    "stage_name": stage.name,
                    "existing_stages": [s.name for s in self.stages],
                    "operation": "add_stage",
                },
            )
        self.stages.append(stage)
        self.stage_registry[stage.name] = stage
        return self

    def get_stage(self, stage_name: str) -> Optional[StageConfig]:
        """Get a stage by name."""
        return self.stage_registry.get(stage_name)

    def remove_stage(self, stage_name: str) -> "PipelineConfig":
        """Remove a stage from the pipeline."""
        self.stages = [s for s in self.stages if s.name != stage_name]
        self.stage_registry.pop(stage_name, None)
        return self

    def validate_dependencies(self) -> bool:
        """Validate stage dependencies are satisfied."""
        stage_names = {stage.name for stage in self.stages}
        for stage in self.stages:
            for dependency in stage.depends_on:
                if dependency not in stage_names:
                    raise ConfigValidationError(
                        "stage_dependency",
                        f"Stage '{stage.name}' depends on undefined stage '{dependency}'",
                        context={
                            "stage_name": stage.name,
                            "undefined_dependency": dependency,
                            "defined_stages": list(stage_names),
                            "operation": "validate_dependencies",
                        },
                    )
        return True

    def get_execution_order(self) -> List[str]:
        """Get stage execution order based on dependencies."""
        visited = set()
        temp_visited = set()
        result = []

        def visit(stage_name: str):
            if stage_name in temp_visited:
                raise WorkflowError(
                    f"Circular dependency detected involving stage '{stage_name}'",
                    context={
                        "stage_name": stage_name,
                        "temp_visited": list(temp_visited),
                        "operation": "get_execution_order",
                    },
                )
            if stage_name in visited:
                return
            temp_visited.add(stage_name)
            stage = self.get_stage(stage_name)
            if stage:
                for dependency in stage.depends_on:
                    visit(dependency)
            temp_visited.remove(stage_name)
            visited.add(stage_name)
            result.append(stage_name)

        for stage in self.stages:
            if stage.name not in visited:
                visit(stage.name)
        return result


class PipelineRegistry(BaseModel):
    """Registry for pipeline configurations."""

    pipelines: Dict[str, PipelineConfig] = Field(default_factory=dict)
    workflows: Dict[str, WorkflowConfig] = Field(default_factory=dict)
    default_pipeline: Optional[str] = Field(default=None)

    def register_pipeline(self, name: str, config: PipelineConfig):
        """Register a pipeline configuration."""
        self.pipelines[name] = config

    def register_workflow(self, name: str, config: WorkflowConfig):
        """Register a workflow configuration."""
        self.workflows[name] = config

    def get_pipeline(self, name: str) -> Optional[PipelineConfig]:
        """Get a pipeline configuration."""
        return self.pipelines.get(name)

    def get_workflow(self, name: str) -> Optional[WorkflowConfig]:
        """Get a workflow configuration."""
        return self.workflows.get(name)

    def list_pipelines(self) -> List[str]:
        """List all registered pipeline names."""
        return list(self.pipelines.keys())

    def list_workflows(self) -> List[str]:
        """List all registered workflow names."""
        return list(self.workflows.keys())


__all__ = [
    "ExecutionMode",
    "ErrorHandlingStrategy",
    "StageType",
    "StageConfig",
    "AgentStageConfig",
    "WorkflowConfig",
    "PipelineConfig",
    "PipelineRegistry",
]
