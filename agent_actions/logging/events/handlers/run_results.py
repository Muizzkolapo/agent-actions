"""Run results collector handler."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent


@dataclass
class ActionResult:
    """Result data for a single action execution."""

    unique_id: str
    action_name: str
    action_index: int
    status: str  # "success", "skipped", "error", "running"
    execution_time: float = 0.0
    output_folder: str = ""
    record_count: int = 0
    tokens: dict[str, int] = field(default_factory=dict)
    error_message: str = ""
    skip_reason: str = ""
    empty_output_records: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    guard_stats: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "unique_id": self.unique_id,
            "action_name": self.action_name,
            "action_index": self.action_index,
            "status": self.status,
            "execution_time": self.execution_time,
            "output_folder": self.output_folder,
            "record_count": self.record_count,
            "tokens": self.tokens,
            "error_message": self.error_message if self.error_message else None,
            "skip_reason": self.skip_reason if self.skip_reason else None,
            "empty_output_records": self.empty_output_records,
            "timing": {
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            },
        }
        if self.guard_stats is not None:
            result["guard_stats"] = self.guard_stats
        return result


class RunResultsCollector:
    """Collects workflow execution results and writes run_results.json."""

    def __init__(
        self,
        output_dir: str | Path | None = None,
        workflow_name: str = "",
    ) -> None:
        self.output_dir = Path(output_dir) if output_dir else None
        self.workflow_name = workflow_name

        self._results: dict[str, ActionResult] = {}
        self._metadata: dict[str, Any] = {
            "invocation_id": None,
            "workflow_name": workflow_name,
            "action_count": 0,
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

    def accepts(self, event: BaseEvent) -> bool:
        """Accept workflow, action, RecordEmptyOutput, and ResultCollectionComplete events."""
        if event.category in ("workflow", "action"):
            return True
        if event.event_type in ("RecordEmptyOutputEvent", "ResultCollectionCompleteEvent"):
            return True
        return False

    def handle(self, event: BaseEvent) -> None:
        """Process an event and update collection state."""
        event_type = event.event_type

        if event.meta.invocation_id and not self._metadata["invocation_id"]:
            self._metadata["invocation_id"] = event.meta.invocation_id

        if event_type == "WorkflowStartEvent":
            self._handle_workflow_start(event)
        elif event_type == "WorkflowCompleteEvent":
            self._handle_workflow_complete(event)
        elif event_type == "WorkflowFailedEvent":
            self._handle_workflow_failed(event)
        elif event_type == "ActionStartEvent":
            self._handle_action_start(event)
        elif event_type == "ActionCompleteEvent":
            self._handle_action_complete(event)
        elif event_type == "ActionSkipEvent":
            self._handle_action_skip(event)
        elif event_type == "ActionFailedEvent":
            self._handle_action_failed(event)
        elif event_type == "ResultCollectionCompleteEvent":
            self._handle_result_collection_complete(event)
        elif event_type == "RecordEmptyOutputEvent":
            self._handle_empty_output(event)

    def flush(self) -> None:
        """Write run_results.json to disk."""
        if not self.output_dir:
            return

        target_dir = self.output_dir / "target"
        target_dir.mkdir(parents=True, exist_ok=True)

        output = {
            "metadata": self._metadata,
            "results": [
                r.to_dict() for r in sorted(self._results.values(), key=lambda x: x.action_index)
            ],
            "elapsed_time": self._metadata["elapsed_time"],
            "tokens": self._total_tokens,
        }

        output_path = target_dir / "run_results.json"
        fd, tmp = tempfile.mkstemp(dir=str(target_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, default=str)
            os.replace(tmp, str(output_path))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _handle_workflow_start(self, event: BaseEvent) -> None:
        self._metadata["workflow_name"] = event.data.get("workflow_name", "")
        self._metadata["action_count"] = event.data.get("action_count", 0)
        self._metadata["execution_mode"] = event.data.get("execution_mode", "sequential")
        self._metadata["started_at"] = (
            event.meta.timestamp.isoformat()
            if event.meta.timestamp
            else datetime.now(UTC).isoformat()
        )
        self._metadata["status"] = "running"
        self.workflow_name = self._metadata["workflow_name"]

    def _handle_workflow_complete(self, event: BaseEvent) -> None:
        self._metadata["completed_at"] = (
            event.meta.timestamp.isoformat()
            if event.meta.timestamp
            else datetime.now(UTC).isoformat()
        )
        self._metadata["elapsed_time"] = event.data.get("elapsed_time", 0.0)
        self._metadata["status"] = "success"
        self.flush()

    def _handle_workflow_failed(self, event: BaseEvent) -> None:
        self._metadata["completed_at"] = (
            event.meta.timestamp.isoformat()
            if event.meta.timestamp
            else datetime.now(UTC).isoformat()
        )
        self._metadata["elapsed_time"] = event.data.get("elapsed_time", 0.0)
        self._metadata["status"] = "error"
        self._metadata["error"] = {
            "message": event.data.get("error_message", ""),
            "type": event.data.get("error_type", ""),
            "failed_action": event.data.get("failed_action", ""),
        }
        self.flush()

    def _handle_action_start(self, event: BaseEvent) -> None:
        action_name = event.data.get("action_name", "")

        if action_name not in self._results:
            unique_id = f"{self.workflow_name}.{action_name}"
            self._results[action_name] = ActionResult(
                unique_id=unique_id,
                action_name=action_name,
                action_index=event.data.get("action_index", 0),
                status="running",
            )

        result = self._results[action_name]
        result.action_index = event.data.get("action_index", result.action_index)
        result.started_at = event.meta.timestamp

    def _handle_action_complete(self, event: BaseEvent) -> None:
        action_name = event.data.get("action_name", "")

        if action_name not in self._results:
            unique_id = f"{self.workflow_name}.{action_name}"
            self._results[action_name] = ActionResult(
                unique_id=unique_id,
                action_name=action_name,
                action_index=event.data.get("action_index", 0),
                status="success",
            )

        result = self._results[action_name]
        result.action_index = event.data.get("action_index", result.action_index)
        result.status = "success"
        result.execution_time = event.data.get("execution_time", 0.0)
        result.output_folder = event.data.get("output_path", "")
        result.record_count = event.data.get("record_count", 0)
        result.tokens = event.data.get("tokens", {})
        result.completed_at = event.meta.timestamp

        tokens = event.data.get("tokens", {})
        self._total_tokens["prompt_tokens"] += tokens.get("prompt_tokens", 0)
        self._total_tokens["completion_tokens"] += tokens.get("completion_tokens", 0)
        self._total_tokens["total_tokens"] += tokens.get("total_tokens", 0)

    def _handle_action_skip(self, event: BaseEvent) -> None:
        action_name = event.data.get("action_name", "")

        if action_name in self._results:
            result = self._results[action_name]
            result.action_index = event.data.get("action_index", result.action_index)
            result.status = "skipped"
            result.skip_reason = event.data.get("skip_reason", "")
            result.completed_at = event.meta.timestamp
        else:
            unique_id = f"{self.workflow_name}.{action_name}"
            self._results[action_name] = ActionResult(
                unique_id=unique_id,
                action_name=action_name,
                action_index=event.data.get("action_index", 0),
                status="skipped",
                skip_reason=event.data.get("skip_reason", ""),
                completed_at=event.meta.timestamp,
            )

    def _handle_action_failed(self, event: BaseEvent) -> None:
        action_name = event.data.get("action_name", "")

        error_msg = event.data.get("error_detail") or event.data.get("error_message", "")

        if action_name in self._results:
            result = self._results[action_name]
            result.action_index = event.data.get("action_index", result.action_index)
            result.status = "error"
            result.execution_time = event.data.get("execution_time", 0.0)
            result.error_message = error_msg
            result.completed_at = event.meta.timestamp
        else:
            unique_id = f"{self.workflow_name}.{action_name}"
            self._results[action_name] = ActionResult(
                unique_id=unique_id,
                action_name=action_name,
                action_index=event.data.get("action_index", 0),
                status="error",
                execution_time=event.data.get("execution_time", 0.0),
                error_message=error_msg,
                completed_at=event.meta.timestamp,
            )

    def _handle_result_collection_complete(self, event: BaseEvent) -> None:
        action_name = event.data.get("action_name", "")
        total_filtered = event.data.get("total_filtered", 0)
        guard_condition = event.data.get("guard_condition", "")

        if action_name not in self._results:
            return

        if not total_filtered and not guard_condition:
            return

        total_success = event.data.get("total_success", 0)

        self._results[action_name].guard_stats = {
            "condition": guard_condition,
            "passed": total_success,
            "filtered": total_filtered,
            "on_false": event.data.get("guard_on_false", ""),
        }

    def _handle_empty_output(self, event: BaseEvent) -> None:
        action_name = event.data.get("action_name", "")
        if action_name not in self._results:
            unique_id = f"{self.workflow_name}.{action_name}"
            # action_index defaults to 0 — RecordEmptyOutputEvent doesn't carry it.
            # ActionCompleteEvent will overwrite with the real index when it arrives.
            self._results[action_name] = ActionResult(
                unique_id=unique_id,
                action_name=action_name,
                action_index=0,
                status="running",
            )
        self._results[action_name].empty_output_records += 1

    def get_summary(self) -> dict[str, int]:
        """Return counts by status: success, skipped, error, running."""
        summary = {"success": 0, "skipped": 0, "error": 0, "running": 0}
        for result in self._results.values():
            if result.status in summary:
                summary[result.status] += 1
        return summary
