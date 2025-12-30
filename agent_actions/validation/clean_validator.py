"""Clean command validation module."""

from pydantic import BaseModel, Field


class CleanCommandArgs(BaseModel):
    """Pydantic model for the clean command arguments."""

    agent: str = Field(..., description="Name of the agent whose workspace should be cleaned.")
    force: bool = Field(False, description="Skip interactive confirmation.")
    all: bool = Field(False, description="Remove all directories including staging.")
