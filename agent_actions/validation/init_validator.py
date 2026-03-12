"""Init command validation module."""

from pydantic import BaseModel, DirectoryPath, Field


class InitCommandArgs(BaseModel):
    """Pydantic model for the init command arguments."""

    project_name: str = Field(..., min_length=1, description="Name of the project to create.")
    output_dir: DirectoryPath | None = Field(
        None, description="Directory to create the project in (default: current directory)."
    )
    template: str = Field("default", description="Template to use for project initialization.")
    force: bool = Field(False, description="Force project creation even if directory exists.")
