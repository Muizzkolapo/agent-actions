
from pydantic import BaseModel, FilePath, DirectoryPath, Field
from typing import Optional

class RunCommandArgs(BaseModel):
    """Pydantic model for the run command arguments."""
    agent: str = Field(..., description="Agent configuration file name without path or extension")
    user_code: Optional[DirectoryPath] = Field(None, description="Path to the user's code folder containing UDFs")
    use_tools: bool = Field(False, description="Enable tool usage for agents")
    force: bool = Field(False, description="Force execution even if validation warnings occur")
