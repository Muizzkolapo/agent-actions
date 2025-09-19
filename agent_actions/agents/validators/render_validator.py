
from pydantic import BaseModel, Field, FilePath, DirectoryPath
from typing import Optional

class RenderCommandArgs(BaseModel):
    """Pydantic model for the render command arguments."""
    agent_name: str = Field(..., description="Name of the agent to render template for")
    output_file: Optional[FilePath] = Field(None, description="Path to save the rendered template (default: output to console)")
    template_dir: Optional[DirectoryPath] = Field(None, description="Directory containing templates (default: ./templates)")
