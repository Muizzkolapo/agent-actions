"""Interactive TUI for ``agac inspect`` — navigate the pipeline, drill
into per-action detail, return to overview.

Single full-screen Rich ``Live`` region with a Layout for header /
body / footer. Raw-mode stdin captures keypresses one at a time:
arrow keys + vim h/j/k/l + Enter + q/Esc.

Static rendering is the ground truth — every TUI screen renders by
calling back into the same definition-list / pipeline-view helpers
that ``agac inspect --json`` and the static commands use. The TUI is
purely a presentation layer; if it fails to import or the terminal
doesn't support raw mode, the caller falls back to static output.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from rich.align import Align
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from agent_actions.services.workflow_inspector import WorkflowInspector


@dataclass
class Step:
    """One row in the pipeline view — a parallel fan-out OR a chain of
    consecutive single-action levels collapsed into one entry.
    """

    kind: str  # "parallel" | "serial"
    actions: list[str] = field(default_factory=list)


def build_steps(levels: list[list[str]]) -> list[Step]:
    """Same collapsing rule as the static `_build_steps` in inspect.py —
    serial singletons chain, parallels stand alone.
    """
    steps: list[Step] = []
    idx = 0
    while idx < len(levels):
        level = levels[idx]
        if len(level) > 1:
            steps.append(Step("parallel", list(level)))
            idx += 1
            continue
        chain = [level[0]]
        while idx + 1 < len(levels) and len(levels[idx + 1]) == 1:
            idx += 1
            chain.append(levels[idx][0])
        steps.append(Step("serial", chain))
        idx += 1
    return steps


def collapse_versions(actions: list[str]) -> list[str]:
    """`foo_1, foo_2, foo_3` → `foo (×3)`.  Same rule as static view."""
    import re

    pattern = re.compile(r"^(.+)_(\d+)$")
    slots: dict[str, int] = {}
    counts: dict[str, int] = {}
    result: list[str] = []
    for name in actions:
        match = pattern.match(name)
        if match:
            base = match.group(1)
            if base in slots:
                counts[base] += 1
            else:
                slots[base] = len(result)
                counts[base] = 1
                result.append(name)
        else:
            result.append(name)
    for base, count in counts.items():
        if count >= 2:
            result[slots[base]] = f"{base} (×{count})"
    return result


# ── Key reading ────────────────────────────────────────────────────


@contextmanager
def raw_mode(file):
    """Put stdin in raw mode so we can read one keystroke at a time
    without waiting for Enter. POSIX only — the caller checks for
    Windows / non-TTY contexts and falls back to static output.
    """
    import termios
    import tty

    fd = file.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_key() -> str:
    """Read one logical keystroke, decoding the common ANSI arrow-key
    escape sequences into named tokens (``up`` / ``down`` / ...).
    """
    ch = sys.stdin.read(1)
    if ch == "\x1b":  # ESC — could be lone Esc or start of CSI sequence
        ch2 = sys.stdin.read(1)
        if ch2 != "[":
            return "esc"
        ch3 = sys.stdin.read(1)
        return {"A": "up", "B": "down", "C": "right", "D": "left"}.get(ch3, "esc")
    if ch in ("\r", "\n"):
        return "enter"
    if ch == "\x03":  # Ctrl-C
        return "ctrl-c"
    return ch


def tui_available() -> bool:
    """True iff we can run a TUI here — POSIX, real TTY on stdin AND stdout."""
    if sys.platform == "win32":
        return False
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    try:
        import termios  # noqa: F401
        import tty  # noqa: F401
    except ImportError:
        return False
    return True


# ── TUI ────────────────────────────────────────────────────────────


class InspectTUI:
    """Interactive inspect — pipeline view + per-step drill-down."""

    def __init__(self, inspector: WorkflowInspector):
        self.inspector = inspector
        self.console = Console()
        self.cursor = 0
        self.screen = "pipeline"
        self.drill_action: str | None = None
        self.steps: list[Step] = []
        self.scope_summary: dict[str, dict[str, Any]] = {}
        self.estimate: dict[str, Any] = {}

    # ── Lifecycle ─────────────────────────────────────────────────

    def run(self) -> None:
        self.steps = build_steps(self.inspector.get_levels())
        self.scope_summary = self.inspector.get_context_scope()
        self.estimate = self.inspector.estimate()

        with raw_mode(sys.stdin):
            with Live(
                self._render(),
                console=self.console,
                screen=True,
                auto_refresh=False,
                transient=False,
            ) as live:
                while True:
                    key = read_key()
                    if not self._handle_key(key):
                        break
                    live.update(self._render(), refresh=True)

    # ── Input ─────────────────────────────────────────────────────

    def _handle_key(self, key: str) -> bool:
        """Return False to quit."""
        if key in ("q", "ctrl-c"):
            return False
        if key == "esc":
            if self.screen == "action":
                self.screen = "pipeline"
                self.drill_action = None
                return True
            return False
        if self.screen == "pipeline":
            return self._handle_pipeline_key(key)
        if self.screen == "action":
            return self._handle_action_key(key)
        return True

    def _handle_pipeline_key(self, key: str) -> bool:
        if key in ("up", "k"):
            self.cursor = max(0, self.cursor - 1)
        elif key in ("down", "j"):
            self.cursor = min(len(self.steps) - 1, self.cursor + 1)
        elif key in ("g",):
            self.cursor = 0
        elif key in ("G",):
            self.cursor = len(self.steps) - 1
        elif key == "enter":
            step = self.steps[self.cursor]
            if step.actions:
                # Drill into the first action of the step. For parallel
                # groups the user can cycle members with h/l, but the
                # opening pick is "first listed".
                self.drill_action = step.actions[0]
                self.screen = "action"
        return True

    def _handle_action_key(self, key: str) -> bool:
        step = self.steps[self.cursor]
        if not step.actions or self.drill_action is None:
            return True
        if key in ("h", "left"):
            idx = step.actions.index(self.drill_action)
            self.drill_action = step.actions[(idx - 1) % len(step.actions)]
        elif key in ("l", "right"):
            idx = step.actions.index(self.drill_action)
            self.drill_action = step.actions[(idx + 1) % len(step.actions)]
        return True

    # ── Render ────────────────────────────────────────────────────

    def _render(self) -> Layout:
        layout = Layout()
        layout.split(
            Layout(self._render_header(), name="header", size=4),
            Layout(self._render_body(), name="body"),
            Layout(self._render_footer(), name="footer", size=1),
        )
        return layout

    def _render_header(self) -> Panel:
        name = self.inspector.agent_name
        action_count = sum(len(s.actions) for s in self.steps)
        title = Text()
        title.append(name, style="bold cyan")
        title.append("   ", style="")
        title.append("✅ validated", style="bold green")
        sub = Text(
            f"{action_count} actions in {len(self.inspector.execution_order)} levels"
            f"  ·  {self.estimate['llm_calls']} LLM calls,"
            f" {self.estimate['guarded_actions']} guarded",
            style="dim",
        )
        return Panel(Group(title, sub), border_style="dim", padding=(0, 1))

    def _render_body(self) -> Panel:
        if self.screen == "pipeline":
            return self._render_pipeline_body()
        return self._render_action_body()

    def _render_pipeline_body(self) -> Panel:
        rows: list[Text] = []
        step_width = max(len(str(len(self.steps))), 1)

        for i, step in enumerate(self.steps):
            row = Text()
            marker = "▶" if i == self.cursor else " "
            row.append(f"{marker} ", style="bold cyan" if i == self.cursor else "")
            row.append(f"{i + 1:>{step_width}}.", style="dim")
            row.append("  ")
            if step.kind == "parallel":
                names = ", ".join(collapse_versions(step.actions))
                row.append("⫻ ", style="bold yellow")
                row.append(names)
            else:
                row.append("  ")
                row.append(step.actions[0])
                for n in step.actions[1:]:
                    row.append(" → ", style="dim")
                    row.append(n)
            rows.append(row)

        return Panel(
            Group(*rows),
            title="[bold]Pipeline[/bold]",
            title_align="left",
            border_style="dim",
            padding=(0, 1),
        )

    def _render_action_body(self) -> Panel:
        from agent_actions.cli.inspect_action import ActionCommand
        from agent_actions.cli.inspect_base import BaseInspectCommand

        # Reuse the existing action-detail rendering by routing it
        # through a capturing console so we can embed in a panel.
        if self.drill_action is None:
            return Panel(Text("no action selected"), border_style="dim")

        capture = Console(record=True, force_terminal=True, width=self.console.width - 4)
        cmd = ActionCommand.__new__(ActionCommand)
        BaseInspectCommand.__init__(cmd, self.drill_action, user_code=None, json_output=False)
        cmd.console = capture
        cmd.schema_service = self.inspector.schema_service
        cmd.action_name = self.drill_action
        action_config = self.inspector.action_configs.get(self.drill_action, {})
        info = cmd._analyze_dependencies(self.inspector)[self.drill_action]
        cmd._output_rich(action_config, info)
        rendered = capture.export_text(styles=True, clear=True)

        # Show siblings of the same parallel group for navigation.
        step = self.steps[self.cursor]
        siblings = ""
        if step.kind == "parallel" and len(step.actions) > 1:
            members = " · ".join(
                f"[bold]{n}[/bold]" if n == self.drill_action else f"[dim]{n}[/dim]"
                for n in step.actions
            )
            siblings = f"\n[dim]siblings:[/dim]  {members}\n"

        title = f"[bold]Action[/bold]  [dim](step {self.cursor + 1})[/dim]"
        return Panel(
            Text.from_ansi(rendered + siblings),
            title=title,
            title_align="left",
            border_style="dim",
            padding=(0, 1),
        )

    def _render_footer(self) -> Align:
        if self.screen == "pipeline":
            hint = "[dim]↑/↓ navigate  ·  ↵ drill in  ·  q quit[/dim]"
        else:
            hint = "[dim]←/→ siblings  ·  esc back  ·  q quit[/dim]"
        return Align(Text.from_markup(hint), align="left")
