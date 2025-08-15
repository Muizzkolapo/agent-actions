"""Validation results artifact."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseArtifact, ArtifactMetadata


class ValidationResultsArtifact(BaseArtifact):
    """Stores validation attempts for agents."""

    def __init__(self, metadata: Optional[ArtifactMetadata] = None) -> None:
        super().__init__(metadata)
        self.results: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    def add_attempt(
        self,
        agent_id: str,
        validator_type: str,
        attempt: int,
        status: str,
        error: Optional[str] = None,
        response: Optional[str] = None,
    ) -> None:
        agent_entry = self.results.setdefault(agent_id, {})
        validator_entry = agent_entry.setdefault(validator_type, [])
        validator_entry.append(
            {
                "attempt": attempt,
                "status": status,
                "error": error,
                "response": response,
            }
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"metadata": self.metadata.to_dict(), "results": self.results}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ValidationResultsArtifact":
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
        # CRITICAL FIX: Properly restore results data
        obj.results = data.get("results", {})
        return obj
