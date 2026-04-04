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
from rich.text import Text

logger = logging.getLogger(__name__)

# ── Snapshot dataclasses ──────────────────────────────────────────────


@dataclass
class ActionResult:
    """Per-action execution result for rendering."""

    name: str
    kind: str  # "llm", "tool", "hitl", "source", "seed"
    status: str  # ActionStatus value
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

    # Workflow version from the raw YAML config
    version = ""
    try:
        user_config = workflow.config.manager.user_config
        if isinstance(user_config, dict):
            version = str(user_config.get("version", ""))
    except Exception:
        pass

    results: dict[str, ActionResult] = {}
    for action_name, config in action_configs.items():
        status = state_mgr.get_status(action_name).value
        details = state_mgr.get_status_details(action_name)

        kind = config.get("type", config.get("agent_type", "llm"))
        # Normalise kind — the config may store it as agent_type value
        if kind in ("tool", "hitl", "source", "seed"):
            pass
        else:
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
    "gate": ("gate", "bold black on yellow"),
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
_BOX_RT = "┤"


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

    # ── Header ────────────────────────────────────────────────────

    def _render_header(self, snap: WorkflowExecutionSnapshot) -> None:
        title = Text()
        title.append("◆ ", style="bold blue")
        title.append(snap.workflow_name, style="bold white")
        if snap.workflow_version:
            title.append(f"  v{snap.workflow_version}", style="dim")
        self.console.print(title)

        # Stats line
        results = snap.action_results
        kind_counts = Counter(r.kind for r in results.values())
        total = len(results)
        vendors = len({r.model_vendor for r in results.values() if r.model_vendor})

        parts = [f"{total} actions"]
        if vendors:
            parts.append(f"{vendors} vendors")
        for kind in ("llm", "tool", "hitl"):
            if kind_counts.get(kind):
                parts.append(f"{kind_counts[kind]} {kind}")

        stats = Text(" · ".join(parts), style="dim")
        self.console.print(stats)
        self.console.print(Text(_BOX_H * min(60, self.console.width - 2), style="dim"))

    # ── Level rendering ───────────────────────────────────────────

    def _render_levels(self, snap: WorkflowExecutionSnapshot) -> None:
        levels = snap.execution_levels
        for i, level in enumerate(levels):
            is_last = i == len(levels) - 1
            is_parallel = len(level) > 1

            if is_parallel:
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
        line = self._format_action_line(result, connector)
        self.console.print(line)
        self._render_sub_status(result, is_last)

    def _render_parallel_level(
        self, actions: list[str], snap: WorkflowExecutionSnapshot, is_last: bool
    ) -> None:
        prefix = "  " if is_last else f"{_BOX_V} "

        # Top border
        inner_w = min(55, self.console.width - 8)
        self.console.print(
            Text(f"{prefix} {_BOX_TL}{_BOX_H * inner_w}{_BOX_TR}", style="dim cyan")
        )

        for action_name in actions:
            result = snap.action_results.get(action_name)
            if not result:
                continue
            connector = f"{prefix} {_BOX_V}"
            line = self._format_action_line(result, connector)
            self.console.print(line)

        # Bottom border
        self.console.print(
            Text(f"{prefix} {_BOX_BL}{_BOX_H * inner_w}{_BOX_BR}", style="dim cyan")
        )

    # ── Action line formatting ────────────────────────────────────

    def _format_action_line(self, result: ActionResult, connector: str) -> Text:
        line = Text()

        # Connector
        line.append(connector, style="dim")
        line.append(" ")

        # Status icon
        icon, icon_style = _STATUS_ICONS.get(result.status, ("?", "dim"))
        line.append(icon, style=icon_style)
        line.append(" ")

        # Action name (padded)
        name = result.name
        if len(name) > 28:
            name = name[:25] + "..."
        line.append(f"{name:<28}", style="white")

        # Kind badge
        label, badge_style = _KIND_STYLES.get(result.kind, ("???", "dim"))
        line.append(f" {label:^4} ", style=badge_style)

        # Provider + model
        if result.kind == "llm" and result.model_vendor:
            vendor_short = result.model_vendor[:5]
            model_short = result.model_name[:12] if result.model_name else ""
            meta = f" {vendor_short} {model_short}"
            line.append(meta, style="dim")

        # Latency
        if result.execution_time > 0:
            line.append(f" {result.execution_time:.1f}s", style="dim yellow")

        return line

    def _render_sub_status(self, result: ActionResult, is_last: bool) -> None:
        """Render sub-status lines (skip reason, error)."""
        prefix = "   " if is_last else f"{_BOX_V}  "

        if result.status == "skipped" and result.skip_reason:
            sub = Text(f"{prefix}  ↳ skipped: {result.skip_reason}", style="dim")
            self.console.print(sub)
        elif result.status == "failed" and result.error_message:
            msg = result.error_message[:80]
            sub = Text(f"{prefix}  ↳ error: {msg}", style="red")
            self.console.print(sub)

    # ── Footer ────────────────────────────────────────────────────

    def _render_footer(self, snap: WorkflowExecutionSnapshot) -> None:
        results = snap.action_results
        completed = sum(1 for r in results.values() if r.status == "completed")
        failed = sum(1 for r in results.values() if r.status == "failed")
        skipped = sum(1 for r in results.values() if r.status == "skipped")
        partial = sum(1 for r in results.values() if r.status == "completed_with_failures")

        self.console.print(Text(_BOX_H * min(60, self.console.width - 2), style="dim"))

        footer = Text()
        if failed == 0 and snap.total_elapsed > 0:
            footer.append("✓ ", style="green")
            footer.append(f"Done in {snap.total_elapsed:.1f}s", style="dim")
        elif failed > 0:
            footer.append("✗ ", style="red")
            footer.append(f"{failed} failed", style="red")

        parts = []
        if completed:
            parts.append(f"{completed} completed")
        if partial:
            parts.append(f"{partial} partial")
        if skipped:
            parts.append(f"{skipped} skipped")

        if parts:
            footer.append(f"  ({', '.join(parts)})", style="dim")

        self.console.print(footer)
