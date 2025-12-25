"""Docs command validation module."""

from pydantic import BaseModel, Field


class DocsCommandArgs(BaseModel):
    """Pydantic model for the docs command arguments."""
    host: str = Field(
        "0.0.0.0",
        description="Host for the documentation server."
    )
    port: int = Field(8000, description="Port for the documentation server.")
    debug: bool = Field(False, description="Run the server in debug mode.")
    open_browser: bool = Field(
        True,
        description="Open the browser automatically when the server starts."
    )
