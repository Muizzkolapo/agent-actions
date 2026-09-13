"""Live progress rendering for a workflow run."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_actions.logging.core.handlers.console import ConsoleEventHandler

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent


def _escape(text: str) -> str:
    """Neutralize square brackets so record content cannot be read as markup."""
    from rich.markup import escape

    return escape(str(text))


def _duration(seconds: float) -> str:
    if seconds >= 60:
        return f"{int(seconds // 60)}m{int(seconds % 60):02d}s"
    return f"{seconds:.1f}s"


def _records(count: int) -> str:
    return f"{count} record" if count == 1 else f"{count} records"


class ProgressRenderer(ConsoleEventHandler):
    """Renders workflow, step and action events as one grouped progress stream.

    Anything outside that stream — warnings, errors, verbose diagnostics —
    falls through to plain console formatting so nothing is swallowed.
    """

    _DISPATCH = {
        "WorkflowStartEvent": "_workflow_start",
        "WorkflowCompleteEvent": "_workflow_complete",
        "WorkflowFailedEvent": "_workflow_failed",
        "StepStartEvent": "_step_start",
        "StepCompleteEvent": "_step_complete",
        "ActionStartEvent": "_action_start",
        "ActionCompleteEvent": "_action_complete",
        "ActionSkipEvent": "_action_skip",
        "ActionCachedEvent": "_action_cached",
        "ActionFailedEvent": "_action_failed",
    }

    def handle(self, event: BaseEvent) -> None:
        method = self._DISPATCH.get(event.event_type)
        if method is None:
            super().handle(event)
            return
        line = getattr(self, method)(event)
        if line is not None:
            self._write(line)

    def _style(self, text: str, style: str) -> str:
        return f"[{style}]{text}[/{style}]" if self._use_rich else text

    def _icon(self, rich_icon: str, plain: str, style: str) -> str:
        return self._style(rich_icon, style) if self._use_rich else plain

    # ── workflow ──────────────────────────────────────────────────────

    def _workflow_start(self, event: BaseEvent) -> str:
        name = _escape(event.data.get("workflow_name", ""))
        actions = event.data.get("action_count", 0)
        return f"\n{self._style(name, 'bold')} — {actions} actions"

    def _workflow_complete(self, event: BaseEvent) -> str:
        elapsed = _duration(event.data.get("elapsed_time", 0.0))
        failed = event.data.get("actions_failed", 0)
        parts = [f"{event.data.get('actions_completed', 0)} completed"]
        for label, key in (("partial", "actions_partial"), ("skipped", "actions_skipped")):
            if event.data.get(key, 0):
                parts.append(f"{event.data[key]} {label}")
        if failed:
            parts.append(f"{failed} failed")

        icon = self._icon("✗", "FAILED", "red") if failed else self._icon("✓", "DONE", "green")
        return f"\n{icon} {elapsed} — {', '.join(parts)}"

    def _workflow_failed(self, event: BaseEvent) -> str:
        icon = self._icon("✗", "FAILED", "red")
        message = _escape(event.data.get("error_message", ""))
        return f"\n{icon} {message}"

    # ── steps ─────────────────────────────────────────────────────────

    def _step_start(self, event: BaseEvent) -> str:
        pending = event.data.get("pending", [])
        head = self._style(
            f"Step {event.data.get('step_index', 0)}/{event.data.get('total_steps', 0)}", "cyan"
        )
        if not pending:
            actions = event.data.get("actions", [])
            subject = ", ".join(_escape(a) for a in actions)
            return f"{head} {subject} {self._style('— already complete', 'dim')}"
        if len(pending) > 1:
            return f"{head} {len(pending)} in parallel"
        return f"{head} {_escape(pending[0])}"

    def _step_complete(self, event: BaseEvent) -> str | None:
        # A step's own timing is noise next to its actions'; only say something
        # when the step did not actually finish.
        batch_pending = event.data.get("batch_pending", [])
        if not batch_pending:
            return None
        count = len(batch_pending)
        job = "job" if count == 1 else "jobs"
        return self._style(f"  {count} batch {job} submitted — run again to continue", "yellow")

    # ── actions ───────────────────────────────────────────────────────

    def _subject(self, event: BaseEvent) -> str:
        # Always named, never only in the step header: a reader greps for an
        # action to ask whether it finished, and the answer is this line.
        return f"{_escape(event.data.get('action_name', ''))}  "

    def _action_start(self, event: BaseEvent) -> None:
        # The step header already named what is about to run.
        return None

    def _action_complete(self, event: BaseEvent) -> str:
        detail = [_records(event.data.get("record_count", 0))]
        detail.append(f"in {_duration(event.data.get('execution_time', 0.0))}")
        vendor = event.data.get("model_vendor", "")
        model = event.data.get("model_name", "")
        if vendor and model:
            detail.append(f"({_escape(vendor)}/{_escape(model)})")
        elif vendor:
            detail.append(f"({_escape(vendor)})")
        return f"  {self._icon('✓', 'OK', 'green')} {self._subject(event)}{' '.join(detail)}"

    def _action_skip(self, event: BaseEvent) -> str:
        reason = _escape(event.data.get("skip_reason", ""))
        suffix = f" — {reason}" if reason else ""
        icon = self._icon("○", "SKIP", "dim")
        return f"  {icon} {self._subject(event)}{self._style('skipped' + suffix, 'dim')}"

    def _action_cached(self, event: BaseEvent) -> str:
        icon = self._icon("○", "CACHED", "cyan")
        return f"  {icon} {self._subject(event)}{self._style('cached', 'dim')}"

    def _action_failed(self, event: BaseEvent) -> str:
        message = _escape(event.data.get("error_message", "")) or "failed"
        icon = self._icon("✗", "FAIL", "red")
        line = f"  {icon} {self._subject(event)}{self._style(message, 'red')}"
        suggestion = event.data.get("suggestion", "")
        if suggestion:
            line += "\n    " + self._style(_escape(suggestion), "dim")
        return line


__all__ = ["ProgressRenderer"]
