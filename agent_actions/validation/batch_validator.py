"""Batch command validation module."""

from pydantic import BaseModel, Field


class BatchCommandArgs(BaseModel):
    """Pydantic model for the batch command arguments."""

    batch_id: str | None = Field(None, description="The ID of the batch job.")
