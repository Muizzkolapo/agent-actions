
from pydantic import BaseModel, Field

class StatusCommandArgs(BaseModel):
    """Pydantic model for the status command arguments."""
    agent: str = Field(..., description="Agent configuration file name without path or extension")
