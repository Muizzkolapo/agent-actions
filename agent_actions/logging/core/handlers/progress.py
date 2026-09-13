"""Live progress rendering for a workflow run."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_actions.logging.core.handlers.console import ConsoleEventHandler

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent


def _duration(seconds: float) -> str:
    if seconds >= 60:
        return f"{int(seconds // 60)}m{int(seconds % 60):02d}s"
    return f"{seconds:.1f}s"


def _records(count: int) -> str:
    return f"{count} record" if count == 1 else f"{count} records"


def _actions(count: int) -> str:
    return f"{count} action" if count == 1 else f"{count} actions"


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

    def _escape(self, text: str) -> str:
        """Neutralize brackets so record content cannot be read as markup.

        Only when markup is actually rendered: the escape inserts backslashes,
        and a plain stream would show them.
        """
        if not self._use_rich:
            return str(text)
        from rich.markup import escape

        return escape(str(text))

    def _icon(self, rich_icon: str, plain: str, style: str) -> str:
        return self._style(rich_icon, style) if self._use_rich else plain

    # ── workflow ──────────────────────────────────────────────────────

    def _workflow_start(self, event: BaseEvent) -> str:
        name = self._escape(event.data.get("workflow_name", ""))
        return f"\n{self._style(name, 'bold')} — {_actions(event.data.get('action_count', 0))}"

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
        name = self._escape(event.data.get("workflow_name", ""))
        message = self._escape(event.data.get("error_message", ""))
        return f"\n{icon} {self._style(name, 'bold')} failed — {message}"

    # ── steps ─────────────────────────────────────────────────────────

    _FAN_OUT_NAMES_SHOWN = 4

    def _step_start(self, event: BaseEvent) -> str:
        pending = event.data.get("pending", [])
        # 1-based: a run ending on "Step 11/12" reads as one step short.
        head = self._style(
            f"Step {event.data.get('step_index', 0) + 1}/{event.data.get('total_steps', 0)}", "cyan"
        )
        if not pending:
            actions = event.data.get("actions", [])
            subject = ", ".join(self._escape(a) for a in actions)
            return f"{head} {subject} {self._style('— already complete', 'dim')}"
        if len(pending) == 1:
            return f"{head} {self._escape(pending[0])}"

        shown = [self._escape(a) for a in pending[: self._FAN_OUT_NAMES_SHOWN]]
        names = ", ".join(shown)
        if len(pending) > self._FAN_OUT_NAMES_SHOWN:
            names += f" +{len(pending) - self._FAN_OUT_NAMES_SHOWN} more"
        # Never "in parallel": the same level runs serially under
        # --execution-mode sequential.
        return f"{head} {_actions(len(pending))}: {names}"

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

    def _model(self, event: BaseEvent) -> str:
        """The model behind an action, or nothing when no model ran it.

        A tool or HITL action carries its kind as the vendor and its impl as the
        model, which would render as the action's own name a second time.
        """
        if event.data.get("kind", "") != "llm":
            return ""
        vendor = self._escape(event.data.get("model_vendor", ""))
        model = self._escape(event.data.get("model_name", ""))
        if vendor and model:
            return f"{vendor}/{model}"
        return vendor or model

    def _subject(self, event: BaseEvent) -> str:
        # Always named, never only in the step header: a reader greps for an
        # action to ask whether it finished, and the answer is this line.
        return f"{self._escape(event.data.get('action_name', ''))}  "

    def _action_start(self, event: BaseEvent) -> str | None:
        # The step header already named it, so a normal run reports each action
        # once, on completion. A verbose run wants to see what is in flight.
        if not self.show_diagnostics:
            return None
        return f"  {self._style('→', 'dim')} {self._escape(event.data.get('action_name', ''))}"

    def _action_complete(self, event: BaseEvent) -> str:
        detail = [_records(event.data.get("record_count", 0))]
        elapsed = _duration(event.data.get("execution_time", 0.0))
        # Provider queue time is not the action working; saying so stops a long
        # batch reading as a slow action.
        if event.data.get("mode") == "batch":
            elapsed += " (batch)"
        detail.append(f"in {elapsed}")
        model = self._model(event)
        if model:
            detail.append(f"({model})")
        return f"  {self._icon('✓', 'OK', 'green')} {self._subject(event)}{' '.join(detail)}"

    def _action_skip(self, event: BaseEvent) -> str:
        reason = self._escape(event.data.get("skip_reason", ""))
        suffix = f" — {reason}" if reason else ""
        icon = self._icon("○", "SKIP", "dim")
        return f"  {icon} {self._subject(event)}{self._style('skipped' + suffix, 'dim')}"

    def _action_failed(self, event: BaseEvent) -> str:
        message = self._escape(event.data.get("error_message", "")) or "failed"
        icon = self._icon("✗", "FAIL", "red")
        line = f"  {icon} {self._subject(event)}{self._style(message, 'red')}"
        suggestion = event.data.get("suggestion", "")
        if suggestion:
            line += "\n    " + self._style(self._escape(suggestion), "dim")
        return line


__all__ = ["ProgressRenderer"]
