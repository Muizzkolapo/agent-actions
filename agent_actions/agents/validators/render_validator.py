
from pydantic import BaseModel, Field, FilePath, DirectoryPath, model_validator
from typing import Optional

class RenderCommandArgs(BaseModel):
    """Pydantic model for the render command arguments."""
    agent_name: Optional[str] = Field(None, min_length=1, description="Name of the agent to render template for")
    workflow_name: Optional[str] = Field(None, min_length=1, description="Name of the workflow to render template for")
    output_file: Optional[str] = Field(None, description="Path to save the rendered template (default: output to console)")
    template_dir: Optional[str] = Field(None, description="Directory containing templates (default: ./templates)")

    @model_validator(mode='after')
    def check_mutually_exclusive(self):
        """Ensure exactly one of agent_name or workflow_name is provided."""
        if self.agent_name and self.workflow_name:
            raise ValueError("Cannot specify both agent_name and workflow_name. Please provide only one.")
        if not self.agent_name and not self.workflow_name:
            raise ValueError("Must specify either agent_name (-a) or workflow_name (positional argument).")
        return self
