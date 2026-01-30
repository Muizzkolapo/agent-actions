"""Batch command validation module."""

from typing import Optional

from pydantic import BaseModel, Field


class BatchCommandArgs(BaseModel):
    """Pydantic model for the batch command arguments."""

    batch_id: Optional[str] = Field(None, description="The ID of the batch job.")
