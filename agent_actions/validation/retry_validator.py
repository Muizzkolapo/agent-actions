"""Retry command validation module."""

from pydantic import BaseModel, Field


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
