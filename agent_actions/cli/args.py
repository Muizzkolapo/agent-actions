"""Pydantic argument models for the CLI commands."""

from typing import Literal

from pydantic import BaseModel, DirectoryPath, Field

DEFAULT_POLL_SECONDS = 60


class BatchCommandArgs(BaseModel):
    """Pydantic model for the batch command arguments."""

    batch_id: str | None = Field(None, description="The ID of the batch job.")


class CleanCommandArgs(BaseModel):
    """Pydantic model for the clean command arguments."""

    agent: str = Field(..., description="Name of the agent whose workspace should be cleaned.")
    force: bool = Field(False, description="Skip interactive confirmation.")
    target: bool = Field(False, description="Remove the target directory (generated output).")
    all: bool = Field(False, description="Remove all directories including target and staging.")


class StatusCommandArgs(BaseModel):
    """Pydantic model for the status command arguments."""

    agent: str = Field(
        ..., min_length=1, description="Agent configuration file name without path or extension"
    )
    as_json: bool = Field(False, description="Print each action's status and the run's as JSON.")


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
        description="Specific record source_guid to retry. If omitted, retries all "
        "failed records.",
    )
    dry_run: bool = Field(
        default=False,
        description="Show what would be retried without executing.",
    )
    abandon_in_flight: bool = Field(
        default=False,
        description="Proceed even though a batch has not been collected, giving up its results.",
    )
    filters: list[tuple[str, str]] = Field(
        default_factory=list,
        description="(action, record_id) of each failed record to filter instead of retrying.",
    )
    reason: str | None = Field(
        default=None,
        description="Why the records given to filters are filtered; stored as their reason.",
    )
    all: bool = Field(
        default=False,
        description="Retry again while a pass closes an open failure.",
    )
    max_passes: int | None = Field(
        default=None, ge=1, description="The most passes --all makes; None is no limit."
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
    record_limit: int | None = Field(
        None,
        description="Cap each action at this many records per input file, whatever the "
        "config sets",
        ge=1,
    )
    file_limit: int | None = Field(
        None,
        description="Stop each action after this many input files, whatever the config sets",
        ge=1,
    )
    fresh: bool = Field(False, description="Clear stored results and status before execution")
    refresh_input: bool = Field(
        False, description="Read a database data source again instead of its stored snapshot"
    )
    rerun: tuple[str, ...] = Field(
        (), description="Answer every record of these actions and what reads them again"
    )
    verify_keys: bool = Field(
        False, description="Verify API keys are valid by probing vendor endpoints before execution"
    )
    wait: bool = Field(False, description="Run again while paused for a batch, until none is open")
    poll: int | None = Field(
        None,
        description=(
            "Whole seconds between two passes of --wait. Not given: the default in a real "
            "run, no wait in a sandbox run"
        ),
        ge=1,
    )
    wait_timeout: float | None = Field(
        None, description="Seconds after which --wait stops and leaves the batches open", ge=0
    )
