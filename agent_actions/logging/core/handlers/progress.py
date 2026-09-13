"""Live progress rendering for a workflow run."""

from __future__ import annotations

from agent_actions.logging.core.handlers.console import ConsoleEventHandler


class ProgressRenderer(ConsoleEventHandler):
    """Renders workflow, step and action events as one grouped progress stream."""


__all__ = ["ProgressRenderer"]
