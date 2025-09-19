
from pydantic import BaseModel, Field, DirectoryPath
from typing import Optional

class InitCommandArgs(BaseModel):
    """Pydantic model for the init command arguments."""
    project_name: str = Field(..., description="Name of the project to create.")
    output_dir: Optional[DirectoryPath] = Field(None, description="Directory to create the project in (default: current directory).")
    template: str = Field("default", description="Template to use for project initialization.")
    force: bool = Field(False, description="Force project creation even if directory exists.")
