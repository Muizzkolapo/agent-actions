"""
Agent-actions specific event formatters.

Custom formatters for dbt-style console output of agent-actions events.
These formatters produce clean, scannable output for the CLI.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent

from agent_actions.logging.core._compat import RICH_AVAILABLE


class AgentActionsFormatter:
    """
    Formatter for agent-actions events.

    Produces dbt-style console output:
        10:30:45 | Running workflow my_workflow (5 agents)
        10:30:46 | 1/5 OK extract_data in 12.34s (1700 tokens)
        10:30:47 | 2/5 SKIP transform (cached)
        10:31:00 | Completed in 15.00s | 4 OK | 1 SKIP | 0 ERROR
    """

    # Status colors for Rich
    COLORS = {
        "OK": "green",
        "SKIP": "yellow",
        "CACHED": "cyan",
        "ERROR": "red",
        "START": "blue",
        "WARN": "yellow",
    }

    def __init__(self, show_timestamp: bool = True, use_color: bool = True) -> None:
        """
        Initialize the formatter.

        Args:
            show_timestamp: Include timestamps in output
            use_color: Use Rich colors (if available)
        """
        self.show_timestamp = show_timestamp
        self.use_color = use_color and RICH_AVAILABLE

    def format(self, event: BaseEvent) -> str:
        """
        Format an event for console output.

        Args:
            event: Event to format

        Returns:
            Formatted string for console display
        """
        # Route to specific formatter based on event type
        event_type = event.event_type

        # Workflow events
        if event_type == "WorkflowStartEvent":
            return self._format_workflow_start(event)
        elif event_type == "WorkflowCompleteEvent":
            return self._format_workflow_complete(event)
        elif event_type == "WorkflowFailedEvent":
            return self._format_workflow_failed(event)

        # Agent events
        elif event_type == "AgentStartEvent":
            return self._format_agent_start(event)
        elif event_type == "AgentCompleteEvent":
            return self._format_agent_complete(event)
        elif event_type == "AgentSkipEvent":
            return self._format_agent_skip(event)
        elif event_type == "AgentFailedEvent":
            return self._format_agent_failed(event)
        elif event_type == "AgentCachedEvent":
            return self._format_agent_cached(event)

        # Batch events
        elif event_type == "BatchSubmittedEvent":
            return self._format_batch_submitted(event)
        elif event_type == "BatchCompleteEvent":
            return self._format_batch_complete(event)

        # Default formatting
        else:
            return self._format_default(event)

    def _timestamp(self, event: BaseEvent) -> str:
        """Get formatted timestamp."""
        if not self.show_timestamp:
            return ""
        ts = event.meta.timestamp
        if isinstance(ts, datetime):
            time_str = ts.strftime("%H:%M:%S")
        else:
            time_str = datetime.now().strftime("%H:%M:%S")
        return f"[dim]{time_str}[/dim] | " if self.use_color else f"{time_str} | "

    def _status(self, status: str) -> str:
        """Format a status indicator with color."""
        if self.use_color and status in self.COLORS:
            color = self.COLORS[status]
            return f"[{color}]{status}[/{color}]"
        return status

    def _format_workflow_start(self, event: BaseEvent) -> str:
        """Format WorkflowStartEvent."""
        ts = self._timestamp(event)
        name = event.data.get("workflow_name", "")
        count = event.data.get("agent_count", 0)
        mode = event.data.get("execution_mode", "sequential")

        mode_str = f" [{mode}]" if mode != "sequential" else ""
        return (
            f"{ts}Running workflow [bold]{name}[/bold] ({count} agents){mode_str}"
            if self.use_color
            else f"{ts}Running workflow {name} ({count} agents){mode_str}"
        )

    def _format_workflow_complete(self, event: BaseEvent) -> str:
        """Format WorkflowCompleteEvent."""
        ts = self._timestamp(event)
        elapsed = event.data.get("elapsed_time", 0.0)
        completed = event.data.get("agents_completed", 0)
        skipped = event.data.get("agents_skipped", 0)
        failed = event.data.get("agents_failed", 0)

        ok = self._status("OK") if completed > 0 else "OK"
        skip = self._status("SKIP") if skipped > 0 else "SKIP"
        err = self._status("ERROR") if failed > 0 else "ERROR"

        return f"{ts}Completed in {elapsed:.2f}s | {completed} {ok} | {skipped} {skip} | {failed} {err}"

    def _format_workflow_failed(self, event: BaseEvent) -> str:
        """Format WorkflowFailedEvent."""
        ts = self._timestamp(event)
        name = event.data.get("workflow_name", "")
        error = event.data.get("error_message", "")

        err_status = self._status("ERROR")
        return f"{ts}{err_status} Workflow {name} failed: {error}"

    def _format_agent_start(self, event: BaseEvent) -> str:
        """Format AgentStartEvent."""
        ts = self._timestamp(event)
        idx = event.data.get("agent_index", 0)
        total = event.data.get("total_agents", 0)
        name = event.data.get("agent_name", "")

        idx_str = f"{idx + 1}/{total}"
        start = self._status("START")
        return f"{ts}{idx_str} {start} {name}"

    def _format_agent_complete(self, event: BaseEvent) -> str:
        """Format AgentCompleteEvent."""
        ts = self._timestamp(event)
        idx = event.data.get("agent_index", 0)
        total = event.data.get("total_agents", 0)
        name = event.data.get("agent_name", "")
        time = event.data.get("execution_time", 0.0)
        tokens = event.data.get("tokens", {}).get("total_tokens", 0)

        idx_str = f"{idx + 1}/{total}"
        ok = self._status("OK")
        token_str = f" ({tokens} tokens)" if tokens > 0 else ""
        return f"{ts}{idx_str} {ok} {name} in {time:.2f}s{token_str}"

    def _format_agent_skip(self, event: BaseEvent) -> str:
        """Format AgentSkipEvent."""
        ts = self._timestamp(event)
        idx = event.data.get("agent_index", 0)
        total = event.data.get("total_agents", 0)
        name = event.data.get("agent_name", "")
        reason = event.data.get("skip_reason", "")

        idx_str = f"{idx + 1}/{total}"
        skip = self._status("SKIP")
        reason_str = f" ({reason})" if reason else ""
        return f"{ts}{idx_str} {skip} {name}{reason_str}"

    def _format_agent_cached(self, event: BaseEvent) -> str:
        """Format AgentCachedEvent."""
        ts = self._timestamp(event)
        idx = event.data.get("agent_index", 0)
        total = event.data.get("total_agents", 0)
        name = event.data.get("agent_name", "")

        idx_str = f"{idx + 1}/{total}"
        cached = self._status("CACHED")
        return f"{ts}{idx_str} {cached} {name}"

    def _format_agent_failed(self, event: BaseEvent) -> str:
        """Format AgentFailedEvent."""
        ts = self._timestamp(event)
        idx = event.data.get("agent_index", 0)
        total = event.data.get("total_agents", 0)
        name = event.data.get("agent_name", "")
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
        """Format BatchSubmittedEvent."""
        ts = self._timestamp(event)
        batch_id = event.data.get("batch_id", "")[:8]  # Truncate ID
        count = event.data.get("request_count", 0)
        provider = event.data.get("provider", "")

        return f"{ts}Batch {batch_id} submitted: {count} requests to {provider}"

    def _format_batch_complete(self, event: BaseEvent) -> str:
        """Format BatchCompleteEvent."""
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
        """Default event formatting."""
        ts = self._timestamp(event)
        return f"{ts}{event.message}"
