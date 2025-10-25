"""
Pydantic validators for CLI inspect commands.

This module provides validation schemas for the inspect command arguments
including signatures, field-flow, and conflicts commands.
"""

from pydantic import BaseModel, Field, validator
from typing import Optional


class SignaturesCommandArgs(BaseModel):
    """Pydantic model for the signatures command arguments."""
    
    agent_name: str = Field(..., description="Agent name to inspect")
    format: str = Field(default="table", description="Output format: table or json")
    filter_agent: Optional[str] = Field(default=None, description="Specific agent name to show signatures for")
    
    @validator('format')
    def validate_format(cls, v):
        """Validate the output format is supported."""
        if v not in ['table', 'json']:
            raise ValueError("format must be 'table' or 'json'")
        return v
    
    @validator('agent_name')
    def validate_agent_name(cls, v):
        """Validate the agent name is not empty."""
        if not v or not v.strip():
            raise ValueError("Agent name cannot be empty")
        return v.strip()


class FieldFlowCommandArgs(BaseModel):
    """Pydantic model for the field-flow command arguments."""
    
    agent_name: str = Field(..., description="Agent name to inspect")
    format: str = Field(default="table", description="Output format: table or json")
    
    @validator('format')
    def validate_format(cls, v):
        """Validate the output format is supported."""
        if v not in ['table', 'json']:
            raise ValueError("format must be 'table' or 'json'")
        return v
    
    @validator('agent_name')
    def validate_agent_name(cls, v):
        """Validate the agent name is not empty."""
        if not v or not v.strip():
            raise ValueError("Agent name cannot be empty")
        return v.strip()


class ConflictsCommandArgs(BaseModel):
    """Pydantic model for the conflicts command arguments."""
    
    agent_name: str = Field(..., description="Agent name to inspect")
    filter_agent: Optional[str] = Field(default=None, description="Specific agent name to check for conflicts")
    format: str = Field(default="table", description="Output format: table or json")
    
    @validator('format')
    def validate_format(cls, v):
        """Validate the output format is supported."""
        if v not in ['table', 'json']:
            raise ValueError("format must be 'table' or 'json'")
        return v
    
    @validator('agent_name')
    def validate_agent_name(cls, v):
        """Validate the agent name is not empty."""
        if not v or not v.strip():
            raise ValueError("Agent name cannot be empty")
        return v.strip()