"""
Run results collector handler.

Collects workflow execution data and outputs a run_results.json artifact
similar to dbt's run_results.json. This artifact is useful for:
- CI/CD integration (check success/failure status)
- Analytics and performance tracking
- Debugging and troubleshooting
- Integration with external tools
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent


@dataclass
class AgentResult:
    """Result data for a single agent execution."""

    unique_id: str
    agent_name: str
    agent_index: int
    status: str  # "success", "skipped", "error", "cached"
    execution_time: float = 0.0
    output_folder: str = ""
    record_count: int = 0
    tokens: dict[str, int] = field(default_factory=dict)
    error_message: str = ""
    skip_reason: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "unique_id": self.unique_id,
            "agent_name": self.agent_name,
            "agent_index": self.agent_index,
            "status": self.status,
            "execution_time": self.execution_time,
            "output_folder": self.output_folder,
            "record_count": self.record_count,
            "tokens": self.tokens,
            "error_message": self.error_message if self.error_message else None,
            "skip_reason": self.skip_reason if self.skip_reason else None,
            "timing": {
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            },
        }


class RunResultsCollector:
    """
    Handler that collects workflow execution results into run_results.json.

    Output schema:
    {
        "metadata": {
            "invocation_id": "abc12345",
            "workflow_name": "my_workflow",
            "agent_count": 5,
            "execution_mode": "sequential",
            "started_at": "2024-01-15T10:30:00.000Z",
            "completed_at": "2024-01-15T10:31:23.456Z",
            "elapsed_time": 83.456,
            "status": "success"
        },
        "results": [
            {
                "unique_id": "my_workflow.extract_data",
                "agent_name": "extract_data",
                ...
            }
        ],
        "elapsed_time": 83.456,
        "args": {}
    }
    """

    def __init__(
        self,
        output_dir: str | Path | None = None,
        workflow_name: str = "",
    ) -> None:
        """
        Initialize the run results collector.

        Args:
            output_dir: Directory to write run_results.json (creates target/ subdir)
            workflow_name: Name of the workflow being executed
        """
        self.output_dir = Path(output_dir) if output_dir else None
        self.workflow_name = workflow_name

        # Collection state
        self._results: dict[str, AgentResult] = {}
        self._metadata: dict[str, Any] = {
            "invocation_id": None,
            "workflow_name": workflow_name,
            "agent_count": 0,
            "execution_mode": "sequential",
            "started_at": None,
            "completed_at": None,
            "elapsed_time": 0.0,
            "status": "running",
        }
        self._total_tokens: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def set_output_dir(self, output_dir: str | Path) -> None:
        """Set the output directory after initialization."""
        self.output_dir = Path(output_dir)

    def accepts(self, event: BaseEvent) -> bool:
        """
        Accept workflow and agent events for collection.

        Args:
            event: Event to check

        Returns:
            True for workflow/agent events we track
        """
        # Accept workflow and agent category events
        return event.category in ("workflow", "agent")

    def handle(self, event: BaseEvent) -> None:
        """
        Process an event and update collection state.

        Args:
            event: Event to process
        """
        event_type = event.event_type

        # Capture invocation_id from any event
        if event.meta.invocation_id and not self._metadata["invocation_id"]:
            self._metadata["invocation_id"] = event.meta.invocation_id

        # Route to specific handlers
        if event_type == "WorkflowStartEvent":
            self._handle_workflow_start(event)
        elif event_type == "WorkflowCompleteEvent":
            self._handle_workflow_complete(event)
        elif event_type == "WorkflowFailedEvent":
            self._handle_workflow_failed(event)
        elif event_type == "AgentStartEvent":
            self._handle_agent_start(event)
        elif event_type == "AgentCompleteEvent":
            self._handle_agent_complete(event)
        elif event_type == "AgentSkipEvent":
            self._handle_agent_skip(event)
        elif event_type == "AgentCachedEvent":
            self._handle_agent_cached(event)
        elif event_type == "AgentFailedEvent":
            self._handle_agent_failed(event)

    def flush(self) -> None:
        """Write run_results.json to disk."""
        if not self.output_dir:
            return

        # Create target directory
        target_dir = self.output_dir / "target"
        target_dir.mkdir(parents=True, exist_ok=True)

        # Build output structure
        output = {
            "metadata": self._metadata,
            "results": [r.to_dict() for r in sorted(self._results.values(), key=lambda x: x.agent_index)],
            "elapsed_time": self._metadata["elapsed_time"],
            "tokens": self._total_tokens,
        }

        # Write to file
        output_path = target_dir / "run_results.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, default=str)

    def _handle_workflow_start(self, event: BaseEvent) -> None:
        """Handle WorkflowStartEvent."""
        self._metadata["workflow_name"] = event.data.get("workflow_name", "")
        self._metadata["agent_count"] = event.data.get("agent_count", 0)
        self._metadata["execution_mode"] = event.data.get("execution_mode", "sequential")
        self._metadata["started_at"] = event.meta.timestamp.isoformat() if event.meta.timestamp else datetime.now(timezone.utc).isoformat()
        self._metadata["status"] = "running"
        self.workflow_name = self._metadata["workflow_name"]

    def _handle_workflow_complete(self, event: BaseEvent) -> None:
        """Handle WorkflowCompleteEvent."""
        self._metadata["completed_at"] = event.meta.timestamp.isoformat() if event.meta.timestamp else datetime.now(timezone.utc).isoformat()
        self._metadata["elapsed_time"] = event.data.get("elapsed_time", 0.0)
        self._metadata["status"] = "success"
        self.flush()

    def _handle_workflow_failed(self, event: BaseEvent) -> None:
        """Handle WorkflowFailedEvent."""
        self._metadata["completed_at"] = event.meta.timestamp.isoformat() if event.meta.timestamp else datetime.now(timezone.utc).isoformat()
        self._metadata["elapsed_time"] = event.data.get("elapsed_time", 0.0)
        self._metadata["status"] = "error"
        self._metadata["error"] = {
            "message": event.data.get("error_message", ""),
            "type": event.data.get("error_type", ""),
            "failed_agent": event.data.get("failed_agent", ""),
        }
        self.flush()

    def _handle_agent_start(self, event: BaseEvent) -> None:
        """Handle AgentStartEvent."""
        agent_name = event.data.get("agent_name", "")
        unique_id = f"{self.workflow_name}.{agent_name}"

        self._results[agent_name] = AgentResult(
            unique_id=unique_id,
            agent_name=agent_name,
            agent_index=event.data.get("agent_index", 0),
            status="running",
            started_at=event.meta.timestamp,
        )

    def _handle_agent_complete(self, event: BaseEvent) -> None:
        """Handle AgentCompleteEvent."""
        agent_name = event.data.get("agent_name", "")

        if agent_name in self._results:
            result = self._results[agent_name]
            result.status = "success"
            result.execution_time = event.data.get("execution_time", 0.0)
            result.output_folder = event.data.get("output_path", "")
            result.record_count = event.data.get("record_count", 0)
            result.tokens = event.data.get("tokens", {})
            result.completed_at = event.meta.timestamp

            # Accumulate tokens
            tokens = event.data.get("tokens", {})
            self._total_tokens["prompt_tokens"] += tokens.get("prompt_tokens", 0)
            self._total_tokens["completion_tokens"] += tokens.get("completion_tokens", 0)
            self._total_tokens["total_tokens"] += tokens.get("total_tokens", 0)

    def _handle_agent_skip(self, event: BaseEvent) -> None:
        """Handle AgentSkipEvent."""
        agent_name = event.data.get("agent_name", "")
        unique_id = f"{self.workflow_name}.{agent_name}"

        self._results[agent_name] = AgentResult(
            unique_id=unique_id,
            agent_name=agent_name,
            agent_index=event.data.get("agent_index", 0),
            status="skipped",
            skip_reason=event.data.get("skip_reason", ""),
            completed_at=event.meta.timestamp,
        )

    def _handle_agent_cached(self, event: BaseEvent) -> None:
        """Handle AgentCachedEvent."""
        agent_name = event.data.get("agent_name", "")
        unique_id = f"{self.workflow_name}.{agent_name}"

        self._results[agent_name] = AgentResult(
            unique_id=unique_id,
            agent_name=agent_name,
            agent_index=event.data.get("agent_index", 0),
            status="cached",
            completed_at=event.meta.timestamp,
        )

    def _handle_agent_failed(self, event: BaseEvent) -> None:
        """Handle AgentFailedEvent."""
        agent_name = event.data.get("agent_name", "")

        if agent_name in self._results:
            result = self._results[agent_name]
            result.status = "error"
            result.execution_time = event.data.get("execution_time", 0.0)
            result.error_message = event.data.get("error_message", "")
            result.completed_at = event.meta.timestamp
        else:
            unique_id = f"{self.workflow_name}.{agent_name}"
            self._results[agent_name] = AgentResult(
                unique_id=unique_id,
                agent_name=agent_name,
                agent_index=event.data.get("agent_index", 0),
                status="error",
                execution_time=event.data.get("execution_time", 0.0),
                error_message=event.data.get("error_message", ""),
                completed_at=event.meta.timestamp,
            )

    def get_summary(self) -> dict[str, int]:
        """
        Get a summary of agent results.

        Returns:
            Dict with counts: success, skipped, cached, error
        """
        summary = {"success": 0, "skipped": 0, "cached": 0, "error": 0, "running": 0}
        for result in self._results.values():
            if result.status in summary:
                summary[result.status] += 1
        return summary
