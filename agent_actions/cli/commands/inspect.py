"""
Inspect commands for the Agent Actions CLI.

This module re-exports from agent_actions.cli.inspect for backwards compatibility.
"""

# Re-export from the main inspect module
from agent_actions.cli.inspect import (
    BaseInspectCommand,
    DependenciesCommand,
    GraphCommand,
    ActionCommand,
    inspect,
    dependencies,
    graph,
    action,
)

__all__ = [
    "BaseInspectCommand",
    "DependenciesCommand",
    "GraphCommand",
    "ActionCommand",
    "inspect",
    "dependencies",
    "graph",
    "action",
]
