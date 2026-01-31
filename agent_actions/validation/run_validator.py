"""Run command validation module."""

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, DirectoryPath, Field


class ExecutionMode(str, Enum):
    """Execution mode for agent workflows."""

    AUTO = "auto"
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


class RunCommandArgs(BaseModel):
    """Pydantic model for the run command arguments."""

    agent: str = Field(..., description="Agent configuration file name without path or extension")
    user_code: Optional[DirectoryPath] = Field(
        None, description="Path to the user's code folder containing UDFs"
    )
    use_tools: bool = Field(False, description="Enable tool usage for agents")
    force: bool = Field(False, description="Force execution even if validation warnings occur")
    execution_mode: Literal["auto", "parallel", "sequential"] = Field(
        "auto", description="Execution mode: 'auto' (detect), 'parallel', or 'sequential'"
    )
    concurrency_limit: int = Field(
        5,
        description="Maximum number of agents to run concurrently in parallel execution",
        ge=1,
        le=50,
    )
    upstream: bool = Field(False, description="Recursively execute upstream dependent workflows")
    downstream: bool = Field(
        False, description="Execute all downstream workflows that depend on this workflow"
    )
    debug_context: bool = Field(
        False, description="Show context debug output during execution"
    )
