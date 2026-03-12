"""Render command validation module."""

from pydantic import BaseModel, Field


class RenderCommandArgs(BaseModel):
    """Pydantic model for the render command arguments."""

    agent_name: str = Field(
        ..., min_length=1, description="Name of the agent to render template for"
    )
    template_dir: str | None = Field(
        None, description="Directory containing templates (default: ./templates)"
    )
