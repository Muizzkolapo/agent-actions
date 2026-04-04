"""Rich terminal renderer for post-execution workflow summaries.

Produces a structured visual summary of workflow execution results,
grouped by execution level with per-action status, type badges,
provider info, and latency.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.rule import Rule
from rich.text import Text

logger = logging.getLogger(__name__)

_KNOWN_KINDS = frozenset({"tool", "hitl", "source", "seed"})

# ── Snapshot dataclasses ──────────────────────────────────────────────


@dataclass
class ActionResult:
    """Per-action execution result for rendering."""

    name: str
    kind: str
    status: str
    execution_time: float = 0.0
    model_vendor: str = ""
    model_name: str = ""
    error_message: str = ""
    skip_reason: str = ""


@dataclass
class WorkflowExecutionSnapshot:
    """Frozen execution snapshot consumed by the renderer."""

    workflow_name: str
    workflow_version: str
    execution_levels: list[list[str]]
    action_results: dict[str, ActionResult] = field(default_factory=dict)
    total_elapsed: float = 0.0


# ── Snapshot builder ──────────────────────────────────────────────────


def build_execution_snapshot(
    workflow: Any,
    elapsed: float,
) -> WorkflowExecutionSnapshot:
    """Assemble a render-ready snapshot from a completed workflow.

    Reads action_configs, state_manager, and action_level_orchestrator
    from the workflow object. Does not mutate anything.
    """
    action_configs = workflow.action_configs
    state_mgr = workflow.services.core.state_manager
    levels = workflow.services.core.action_level_orchestrator.compute_execution_levels()

    version = ""
    try:
        user_config = workflow.config.manager.user_config
        if isinstance(user_config, dict):
            version = str(user_config.get("version", ""))
    except Exception as exc:
        logger.debug("Could not read workflow version: %s", exc)

    results: dict[str, ActionResult] = {}
    for action_name, config in action_configs.items():
        details = state_mgr.get_status_details(action_name)
        status = details.get("status", "pending")
        if hasattr(status, "value"):
            status = status.value

        kind = config.get("kind", "llm")
        if kind not in _KNOWN_KINDS:
            kind = "llm"

        results[action_name] = ActionResult(
            name=action_name,
            kind=kind,
            status=status,
            execution_time=details.get("execution_time", 0.0) or 0.0,
            model_vendor=config.get("model_vendor", ""),
            model_name=config.get("model_name", ""),
            error_message=details.get("error_message", ""),
            skip_reason=details.get("skip_reason", ""),
        )

    return WorkflowExecutionSnapshot(
        workflow_name=workflow.agent_name,
        workflow_version=version,
        execution_levels=levels,
        action_results=results,
        total_elapsed=elapsed,
    )


# ── Style constants ──────────────────────────────────────────────────

_STATUS_ICONS = {
    "completed": ("✓", "green"),
    "completed_with_failures": ("◐", "yellow"),
    "failed": ("✗", "red"),
    "skipped": ("○", "dim"),
    "pending": ("·", "dim"),
    "running": ("▸", "cyan"),
    "batch_submitted": ("⏳", "yellow"),
    "checking_batch": ("⏳", "yellow"),
}

_KIND_STYLES = {
    "llm": ("llm", "bold white on blue"),
    "tool": ("tool", "bold white on green"),
    "hitl": ("hitl", "bold white on magenta"),
    "source": ("src", "bold white on cyan"),
    "seed": ("seed", "bold white on cyan"),
}

_BOX_V = "│"
_BOX_TL = "┌"
_BOX_TR = "┐"
_BOX_BL = "└"
_BOX_BR = "┘"
_BOX_H = "─"
_BOX_LT = "├"


# ── Renderer ──────────────────────────────────────────────────────────


class ExecutionRenderer:
    """Renders post-execution workflow summary using Rich."""

    def __init__(self, console: Console):
        self.console = console

    def render(self, snapshot: WorkflowExecutionSnapshot) -> None:
        """Render the complete execution summary."""
        self.console.print()
        self._render_header(snapshot)
        self._render_levels(snapshot)
        self._render_footer(snapshot)
        self.console.print()

    def _render_header(self, snap: WorkflowExecutionSnapshot) -> None:
        title = Text()
        title.append("◆ ", style="bold blue")
        title.append(snap.workflow_name, style="bold white")
        if snap.workflow_version:
            title.append(f"  v{snap.workflow_version}", style="dim")
        self.console.print(title)

        results = snap.action_results
        kind_counts: Counter[str] = Counter()
        vendors: set[str] = set()
        for r in results.values():
            kind_counts[r.kind] += 1
            if r.model_vendor:
                vendors.add(r.model_vendor)

        parts = [f"{len(results)} actions"]
        if vendors:
            parts.append(f"{len(vendors)} vendors")
        for kind in ("llm", "tool", "hitl"):
            if kind_counts[kind]:
                parts.append(f"{kind_counts[kind]} {kind}")

        self.console.print(Text(" · ".join(parts), style="dim"))
        self.console.print(Rule(style="dim"))

    def _render_levels(self, snap: WorkflowExecutionSnapshot) -> None:
        levels = snap.execution_levels
        for i, level in enumerate(levels):
            is_last = i == len(levels) - 1

            if len(level) > 1:
                self._render_parallel_level(level, snap, is_last)
            else:
                self._render_sequential_action(level[0], snap, is_last)

    def _render_sequential_action(
        self, action_name: str, snap: WorkflowExecutionSnapshot, is_last: bool
    ) -> None:
        result = snap.action_results.get(action_name)
        if not result:
            return
        connector = f"{_BOX_BL}{_BOX_H}" if is_last else f"{_BOX_LT}{_BOX_H}"
        self.console.print(self._format_action_line(result, connector))
        self._render_sub_status(result, is_last)

    def _render_parallel_level(
        self, actions: list[str], snap: WorkflowExecutionSnapshot, is_last: bool
    ) -> None:
        prefix = "  " if is_last else f"{_BOX_V} "
        inner_w = min(55, self.console.width - 8)

        self.console.print(
            Text(f"{prefix} {_BOX_TL}{_BOX_H * inner_w}{_BOX_TR}", style="dim cyan")
        )
        for action_name in actions:
            result = snap.action_results.get(action_name)
            if not result:
                continue
            self.console.print(self._format_action_line(result, f"{prefix} {_BOX_V}"))
        self.console.print(
            Text(f"{prefix} {_BOX_BL}{_BOX_H * inner_w}{_BOX_BR}", style="dim cyan")
        )

    def _format_action_line(self, result: ActionResult, connector: str) -> Text:
        line = Text()
        line.append(connector, style="dim")
        line.append(" ")

        icon, icon_style = _STATUS_ICONS.get(result.status, ("?", "dim"))
        line.append(icon, style=icon_style)
        line.append(" ")

        # Pad to 28 chars so type badges align across rows
        name = result.name
        if len(name) > 28:
            name = name[:25] + "..."
        line.append(f"{name:<28}", style="white")

        label, badge_style = _KIND_STYLES.get(result.kind, ("???", "dim"))
        line.append(f" {label:^4} ", style=badge_style)

        if result.kind == "llm" and result.model_vendor:
            line.append(
                f" {result.model_vendor[:5]} {result.model_name[:12] if result.model_name else ''}",
                style="dim",
            )

        if result.execution_time > 0:
            line.append(f" {result.execution_time:.1f}s", style="dim yellow")

        return line

    def _render_sub_status(self, result: ActionResult, is_last: bool) -> None:
        prefix = "   " if is_last else f"{_BOX_V}  "

        if result.status == "skipped" and result.skip_reason:
            self.console.print(Text(f"{prefix}  ↳ skipped: {result.skip_reason}", style="dim"))
        elif result.status == "failed" and result.error_message:
            self.console.print(
                Text(f"{prefix}  ↳ error: {result.error_message[:80]}", style="red")
            )

    def _render_footer(self, snap: WorkflowExecutionSnapshot) -> None:
        status_counts = Counter(r.status for r in snap.action_results.values())

        self.console.print(Rule(style="dim"))

        footer = Text()
        failed = status_counts["failed"]
        if failed == 0 and snap.total_elapsed > 0:
            footer.append("✓ ", style="green")
            footer.append(f"Done in {snap.total_elapsed:.1f}s", style="dim")
        elif failed > 0:
            footer.append("✗ ", style="red")
            footer.append(f"{failed} failed", style="red")

        parts = []
        if status_counts["completed"]:
            parts.append(f"{status_counts['completed']} completed")
        if status_counts["completed_with_failures"]:
            parts.append(f"{status_counts['completed_with_failures']} partial")
        if status_counts["skipped"]:
            parts.append(f"{status_counts['skipped']} skipped")

        if parts:
            footer.append(f"  ({', '.join(parts)})", style="dim")

        self.console.print(footer)
