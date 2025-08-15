"""Execution run results artifact."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import BaseArtifact, ArtifactMetadata


class ExecutionTiming:
    """Track execution timing for a phase."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None

    def start(self) -> None:
        self.started_at = datetime.utcnow().isoformat() + "Z"

    def complete(self) -> None:
        self.completed_at = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class AgentResult:
    """Result of a single agent execution."""

    def __init__(self, unique_id: str) -> None:
        self.unique_id = unique_id
        self.status = "pending"
        self.timing: List[ExecutionTiming] = []
        self.thread_id: Optional[str] = None
        self.execution_time: float = 0.0
        self.message: Optional[str] = None
        self.failures: int = 0
        self.adapter_response: Dict[str, Any] = {}
        self.error_details: Optional[Dict[str, Any]] = None

    def add_timing(self, name: str) -> ExecutionTiming:
        timing = ExecutionTiming(name)
        self.timing.append(timing)
        return timing

    def to_dict(self) -> Dict[str, Any]:
        return {
            "unique_id": self.unique_id,
            "status": self.status,
            "timing": [t.to_dict() for t in self.timing],
            "thread_id": self.thread_id,
            "execution_time": self.execution_time,
            "message": self.message,
            "failures": self.failures,
            "adapter_response": self.adapter_response,
            "error_details": self.error_details,
        }


class RunResultsArtifact(BaseArtifact):
    """Captures execution results and timing information."""

    def __init__(self, metadata: Optional[ArtifactMetadata] = None) -> None:
        super().__init__(metadata)
        self.elapsed_time: float = 0.0
        self.args: Dict[str, Any] = {}
        self.results: List[AgentResult] = []

    def add_result(self, result: AgentResult) -> None:
        self.results.append(result)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "elapsed_time": self.elapsed_time,
            "args": self.args,
            "results": [r.to_dict() for r in self.results],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunResultsArtifact":
        obj = cls()
        obj.elapsed_time = data.get("elapsed_time", 0.0)
        obj.args = data.get("args", {})
        return obj
