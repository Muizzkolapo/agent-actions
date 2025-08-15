"""Base classes for artifact system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import json
import uuid


class ArtifactMetadata:
    """Standard metadata for all artifacts."""

    def __init__(self) -> None:
        self.generated_at = datetime.utcnow().isoformat() + "Z"
        self.agent_actions_version = self._get_version()
        self.invocation_id = str(uuid.uuid4())
        self.schema_version = "1.0.0"

    def _get_version(self) -> str:
        try:
            import agent_actions  # type: ignore
            return getattr(agent_actions, "__version__")
        except Exception:
            return "1.2.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "agent_actions_version": self.agent_actions_version,
            "invocation_id": self.invocation_id,
            "schema_version": self.schema_version,
        }


class BaseArtifact(ABC):
    """Base class for all artifacts."""

    def __init__(self, metadata: Optional[ArtifactMetadata] = None) -> None:
        self.metadata = metadata or ArtifactMetadata()

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Convert artifact to dictionary format."""

    def save(self, path: Path) -> None:
        """Persist artifact to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, default=str)

    @classmethod
    def load(cls, path: Path) -> "BaseArtifact":
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return cls.from_dict(data)

    @classmethod
    @abstractmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseArtifact":
        """Create artifact from dictionary."""
