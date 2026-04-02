"""Agent-actions specific event formatters."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent

from agent_actions.logging.core._compat import RICH_AVAILABLE


class AgentActionsFormatter:
    """Formats agent-actions events for structured console output."""

    # Status colors for Rich
    COLORS = {
        "OK": "green",
        "PARTIAL": "yellow",
        "SKIP": "yellow",
        "CACHED": "cyan",
        "ERROR": "red",
        "START": "blue",
        "WARN": "yellow",
    }

    def __init__(self, show_timestamp: bool = True, use_color: bool = True) -> None:
        self.show_timestamp = show_timestamp
        self.use_color = use_color and RICH_AVAILABLE

    # Dispatch table mapping event types to formatter methods (by name).
    # Looked up in format(); falls back to _format_default for unknown types.
    _DISPATCH: dict[str, str] = {
        "WorkflowStartEvent": "_format_workflow_start",
        "WorkflowCompleteEvent": "_format_workflow_complete",
        "WorkflowFailedEvent": "_format_workflow_failed",
        "ActionStartEvent": "_format_action_start",
        "ActionCompleteEvent": "_format_action_complete",
        "ActionSkipEvent": "_format_action_skip",
        "ActionFailedEvent": "_format_action_failed",
        "ActionCachedEvent": "_format_action_cached",
        "BatchSubmittedEvent": "_format_batch_submitted",
        "BatchCompleteEvent": "_format_batch_complete",
    }

    def format(self, event: BaseEvent) -> str:
        """Format an event for console output."""
        method_name = self._DISPATCH.get(event.event_type)
        if method_name is not None:
            return str(getattr(self, method_name)(event))
        return self._format_default(event)

    def _timestamp(self, event: BaseEvent) -> str:
        """Get formatted timestamp."""
        if not self.show_timestamp:
            return ""
        ts = event.meta.timestamp
        time_str = ts.strftime("%H:%M:%S")
        return f"[dim]{time_str}[/dim] | " if self.use_color else f"{time_str} | "

    def _status(self, status: str) -> str:
        """Format a status indicator with color."""
        if self.use_color and status in self.COLORS:
            color = self.COLORS[status]
            return f"[{color}]{status}[/{color}]"
        return status

    def _format_workflow_start(self, event: BaseEvent) -> str:
        ts = self._timestamp(event)
        name = event.data.get("workflow_name", "")
        count = event.data.get("action_count", 0)
        mode = event.data.get("execution_mode", "sequential")

        mode_str = f" [{mode}]" if mode != "sequential" else ""
        return (
            f"{ts}Running workflow [bold]{name}[/bold] ({count} actions){mode_str}"
            if self.use_color
            else f"{ts}Running workflow {name} ({count} actions){mode_str}"
        )

    def _format_workflow_complete(self, event: BaseEvent) -> str:
        ts = self._timestamp(event)
        elapsed = event.data.get("elapsed_time", 0.0)
        completed = event.data.get("actions_completed", 0)
        partial = event.data.get("actions_partial", 0)
        skipped = event.data.get("actions_skipped", 0)
        failed = event.data.get("actions_failed", 0)

        ok = self._status("OK") if completed > 0 else "OK"
        part = self._status("PARTIAL") if partial > 0 else "PARTIAL"
        skip = self._status("SKIP") if skipped > 0 else "SKIP"
        err = self._status("ERROR") if failed > 0 else "ERROR"

        return (
            f"{ts}Completed in {elapsed:.2f}s | {completed} {ok} | "
            f"{partial} {part} | {skipped} {skip} | {failed} {err}"
        )

    def _format_workflow_failed(self, event: BaseEvent) -> str:
        ts = self._timestamp(event)
        name = event.data.get("workflow_name", "")
        error = event.data.get("error_message", "")

        err_status = self._status("ERROR")
        return f"{ts}{err_status} Workflow {name} failed: {error}"

    def _format_action_start(self, event: BaseEvent) -> str:
        ts = self._timestamp(event)
        idx = event.data.get("action_index", 0)
        total = event.data.get("total_actions", 0)
        name = event.data.get("action_name", "")

        idx_str = f"{idx + 1}/{total}"
        start = self._status("START")
        return f"{ts}{idx_str} {start} {name}"

    def _format_action_complete(self, event: BaseEvent) -> str:
        ts = self._timestamp(event)
        idx = event.data.get("action_index", 0)
        total = event.data.get("total_actions", 0)
        name = event.data.get("action_name", "")
        time = event.data.get("execution_time", 0.0)
        tokens = event.data.get("tokens", {}).get("total_tokens", 0)

        idx_str = f"{idx + 1}/{total}"
        ok = self._status("OK")
        token_str = f" ({tokens} tokens)" if tokens > 0 else ""
        return f"{ts}{idx_str} {ok} {name} in {time:.2f}s{token_str}"

    def _format_action_skip(self, event: BaseEvent) -> str:
        ts = self._timestamp(event)
        idx = event.data.get("action_index", 0)
        total = event.data.get("total_actions", 0)
        name = event.data.get("action_name", "")
        reason = event.data.get("skip_reason", "")

        idx_str = f"{idx + 1}/{total}"
        skip = self._status("SKIP")
        reason_str = f" ({reason})" if reason else ""
        return f"{ts}{idx_str} {skip} {name}{reason_str}"

    def _format_action_cached(self, event: BaseEvent) -> str:
        ts = self._timestamp(event)
        idx = event.data.get("action_index", 0)
        total = event.data.get("total_actions", 0)
        name = event.data.get("action_name", "")

        idx_str = f"{idx + 1}/{total}"
        cached = self._status("CACHED")
        return f"{ts}{idx_str} {cached} {name}"

    def _format_action_failed(self, event: BaseEvent) -> str:
        ts = self._timestamp(event)
        idx = event.data.get("action_index", 0)
        total = event.data.get("total_actions", 0)
        name = event.data.get("action_name", "")
        error = event.data.get("error_message", "")
        suggestion = event.data.get("suggestion", "")

        idx_str = f"{idx + 1}/{total}"
        err = self._status("ERROR")
        msg = f"{ts}{idx_str} {err} {name}: {error}"

        if suggestion:
            if self.use_color:
                msg += f"\n           [dim]Suggestion: {suggestion}[/dim]"
            else:
                msg += f"\n           Suggestion: {suggestion}"

        return msg

    def _format_batch_submitted(self, event: BaseEvent) -> str:
        ts = self._timestamp(event)
        batch_id = event.data.get("batch_id", "")[:8]  # Truncate ID
        count = event.data.get("request_count", 0)
        provider = event.data.get("provider", "")

        return f"{ts}Batch {batch_id} submitted: {count} requests to {provider}"

    def _format_batch_complete(self, event: BaseEvent) -> str:
        ts = self._timestamp(event)
        batch_id = event.data.get("batch_id", "")[:8]
        elapsed = event.data.get("elapsed_time", 0.0)
        failed = event.data.get("failed", 0)

        if failed == 0:
            status = self._status("OK")
        else:
            status = f"{self._status('WARN')} ({failed} failed)"

        return f"{ts}Batch {batch_id} {status} in {elapsed:.2f}s"

    def _format_default(self, event: BaseEvent) -> str:
        ts = self._timestamp(event)
        return f"{ts}{event.message}"
