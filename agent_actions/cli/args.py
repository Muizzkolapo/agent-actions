"""Pydantic argument models for the CLI commands."""

from typing import Literal

from pydantic import BaseModel, DirectoryPath, Field


class BatchCommandArgs(BaseModel):
    """Pydantic model for the batch command arguments."""

    batch_id: str | None = Field(None, description="The ID of the batch job.")


class CleanCommandArgs(BaseModel):
    """Pydantic model for the clean command arguments."""

    agent: str = Field(..., description="Name of the agent whose workspace should be cleaned.")
    force: bool = Field(False, description="Skip interactive confirmation.")
    all: bool = Field(False, description="Remove all directories including staging.")


class StatusCommandArgs(BaseModel):
    """Pydantic model for the status command arguments."""

    agent: str = Field(
        ..., min_length=1, description="Agent configuration file name without path or extension"
    )


class InitCommandArgs(BaseModel):
    """Pydantic model for the init command arguments."""

    project_name: str = Field(..., min_length=1, description="Name of the project to create.")
    output_dir: DirectoryPath | None = Field(
        None, description="Directory to create the project in (default: current directory)."
    )
    template: str = Field("default", description="Template to use for project initialization.")
    force: bool = Field(False, description="Force project creation even if directory exists.")


class RetryCommandArgs(BaseModel):
    """Pydantic model for the retry command arguments."""

    agent: str = Field(
        ..., min_length=1, description="Agent configuration file name without path or extension"
    )
    from_action: str | None = Field(
        default=None,
        description="Action to retry from. If omitted, retries from earliest failure point.",
    )
    record: str | None = Field(
        default=None,
        description="Specific record source_guid to retry. If omitted, retries all failed records.",
    )
    dry_run: bool = Field(
        default=False,
        description="Show what would be retried without executing.",
    )


class RunCommandArgs(BaseModel):
    """Pydantic model for the run command arguments."""

    agent: str = Field(..., description="Agent configuration file name without path or extension")
    user_code: DirectoryPath | None = Field(
        None, description="Path to the user's code folder containing UDFs"
    )
    use_tools: bool = Field(False, description="Enable tool usage for actions")
    execution_mode: Literal["auto", "parallel", "sequential"] = Field(
        "auto", description="Execution mode: 'auto' (detect), 'parallel', or 'sequential'"
    )
    concurrency_limit: int = Field(
        5,
        description="Maximum number of actions to run concurrently in parallel execution",
        ge=1,
        le=50,
    )
    fresh: bool = Field(False, description="Clear stored results and status before execution")
    verify_keys: bool = Field(
        False, description="Verify API keys are valid by probing vendor endpoints before execution"
    )
