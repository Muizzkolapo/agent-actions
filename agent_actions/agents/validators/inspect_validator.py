"""
Pydantic validators for CLI inspect commands.

This module provides validation schemas for the inspect command arguments
including signatures, field-flow, and conflicts commands.
"""

from pydantic import BaseModel, Field, validator
from typing import Optional
from pathlib import Path


class SignaturesCommandArgs(BaseModel):
    """Pydantic model for the signatures command arguments."""
    
    workflow_path: str = Field(..., description="Path to workflow configuration file")
    format: str = Field(default="table", description="Output format: table or json")
    agent: Optional[str] = Field(default=None, description="Specific agent name to show signatures for")
    
    @validator('format')
    def validate_format(cls, v):
        """Validate the output format is supported."""
        if v not in ['table', 'json']:
            raise ValueError("format must be 'table' or 'json'")
        return v
    
    @validator('workflow_path')
    def validate_workflow_path(cls, v):
        """Validate the workflow path exists."""
        path = Path(v)
        if not path.exists():
            raise ValueError(f"Workflow file does not exist: {v}")
        if not path.is_file():
            raise ValueError(f"Workflow path must be a file: {v}")
        return v


class FieldFlowCommandArgs(BaseModel):
    """Pydantic model for the field-flow command arguments."""
    
    workflow_path: str = Field(..., description="Path to workflow configuration file")
    format: str = Field(default="table", description="Output format: table or json")
    
    @validator('format')
    def validate_format(cls, v):
        """Validate the output format is supported."""
        if v not in ['table', 'json']:
            raise ValueError("format must be 'table' or 'json'")
        return v
    
    @validator('workflow_path')
    def validate_workflow_path(cls, v):
        """Validate the workflow path exists."""
        path = Path(v)
        if not path.exists():
            raise ValueError(f"Workflow file does not exist: {v}")
        if not path.is_file():
            raise ValueError(f"Workflow path must be a file: {v}")
        return v


class ConflictsCommandArgs(BaseModel):
    """Pydantic model for the conflicts command arguments."""
    
    workflow_path: str = Field(..., description="Path to workflow configuration file")
    agent_name: Optional[str] = Field(default=None, description="Specific agent name to check for conflicts")
    format: str = Field(default="table", description="Output format: table or json")
    
    @validator('format')
    def validate_format(cls, v):
        """Validate the output format is supported."""
        if v not in ['table', 'json']:
            raise ValueError("format must be 'table' or 'json'")
        return v
    
    @validator('workflow_path')
    def validate_workflow_path(cls, v):
        """Validate the workflow path exists."""
        path = Path(v)
        if not path.exists():
            raise ValueError(f"Workflow file does not exist: {v}")
        if not path.is_file():
            raise ValueError(f"Workflow path must be a file: {v}")
        return v