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
        obj = cls()
        obj.results = data.get("results", {})
        return obj
