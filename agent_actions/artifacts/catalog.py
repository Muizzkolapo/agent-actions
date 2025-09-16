"""Simple agent catalog artifact."""

from __future__ import annotations

from typing import Any, Dict, Optional

from agent_actions.core.contracts.base import BaseArtifact, ArtifactMetadata


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
        # Restore metadata if present
        metadata = None
        if "metadata" in data:
            metadata = ArtifactMetadata()
            metadata_dict = data["metadata"]
            metadata.generated_at = metadata_dict.get("generated_at", metadata.generated_at)
            metadata.agent_actions_version = metadata_dict.get("agent_actions_version", metadata.agent_actions_version)
            metadata.invocation_id = metadata_dict.get("invocation_id", metadata.invocation_id)
            metadata.schema_version = metadata_dict.get("schema_version", metadata.schema_version)
        
        obj = cls(metadata)
        # CRITICAL FIX: Properly restore agents data
        obj.agents = data.get("agents", {})
        return obj
