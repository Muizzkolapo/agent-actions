"""Simple agent catalog artifact."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import BaseArtifact, ArtifactMetadata


class AgentCatalogArtifact(BaseArtifact):
    """Stores metadata about agents."""

    def __init__(self, metadata: Optional[ArtifactMetadata] = None) -> None:
        super().__init__(metadata)
        self.agents: Dict[str, Any] = {}

    def add_agent(self, unique_id: str, info: Dict[str, Any]) -> None:
        self.agents[unique_id] = info

    def to_dict(self) -> Dict[str, Any]:
        return {"metadata": self.metadata.to_dict(), "agents": self.agents}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentCatalogArtifact":
        obj = cls()
        obj.agents = data.get("agents", {})
        return obj
