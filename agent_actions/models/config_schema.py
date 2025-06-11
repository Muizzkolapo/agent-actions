from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any


class DefaultAgentConfig(BaseModel):
    """Default settings applied to each agent configuration."""

    api_key: Optional[str] = None
    model_name: Optional[str] = None
    chunk_config: Optional[Dict[str, Any]] = None
    is_operational: bool = True

    model_config = ConfigDict(extra="allow")


class AgentConfig(BaseModel):
    """Schema for an individual agent configuration entry."""

    agent_type: str
    name: Optional[str] = None
    model_name: Optional[str] = None
    code_path: Optional[str] = None
    dependencies: List[str] = Field(default_factory=list)
    is_operational: bool = True

    model_config = ConfigDict(extra="allow")
