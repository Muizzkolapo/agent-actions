"""Execution run results artifact."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent_actions.core.contracts.base import BaseArtifact, ArtifactMetadata


class ExecutionTiming:
    """Track execution timing for a phase."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None

    def start(self) -> None:
        self.started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def complete(self) -> None:
        self.completed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

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
        obj.elapsed_time = data.get("elapsed_time", 0.0)
        obj.args = data.get("args", {})
        
        # CRITICAL FIX: Restore results data that was being lost
        results_data = data.get("results", [])
        for result_dict in results_data:
            result = AgentResult(result_dict["unique_id"])
            result.status = result_dict.get("status", "pending")
            result.thread_id = result_dict.get("thread_id")
            result.execution_time = result_dict.get("execution_time", 0.0)
            result.message = result_dict.get("message")
            result.failures = result_dict.get("failures", 0)
            result.adapter_response = result_dict.get("adapter_response", {})
            result.error_details = result_dict.get("error_details")
            
            # Restore timing data
            timing_data = result_dict.get("timing", [])
            for timing_dict in timing_data:
                timing = ExecutionTiming(timing_dict["name"])
                timing.started_at = timing_dict.get("started_at")
                timing.completed_at = timing_dict.get("completed_at")
                result.timing.append(timing)
            
            obj.add_result(result)
        
        return obj
