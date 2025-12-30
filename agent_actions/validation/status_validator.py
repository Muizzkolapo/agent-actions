"""Status command validation module."""

from pydantic import BaseModel, Field


class StatusCommandArgs(BaseModel):
    """Pydantic model for the status command arguments."""

    agent: str = Field(
        ..., min_length=1, description="Agent configuration file name without path or extension"
    )
