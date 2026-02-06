"""Run command validation module."""

from typing import Literal, Optional

from pydantic import BaseModel, DirectoryPath, Field


class RunCommandArgs(BaseModel):
    """Pydantic model for the run command arguments."""

    agent: str = Field(..., description="Agent configuration file name without path or extension")
    user_code: Optional[DirectoryPath] = Field(
        None, description="Path to the user's code folder containing UDFs"
    )
    use_tools: bool = Field(False, description="Enable tool usage for agents")
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
