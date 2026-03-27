"""Inspect commands for the Agent Actions CLI."""

import click

# Re-export classes for backward compatibility
from .inspect_action import ActionCommand, ContextCommand, action, context
from .inspect_base import BaseInspectCommand
from .inspect_deps import DependenciesCommand, dependencies
from .inspect_graph import GraphCommand, graph


@click.group(name="inspect")
def inspect():
    """Inspect workflow structure and data flow."""


inspect.add_command(dependencies)
inspect.add_command(graph)
inspect.add_command(action)
inspect.add_command(context)

__all__ = [
    "inspect",
    "BaseInspectCommand",
    "DependenciesCommand",
    "GraphCommand",
    "ActionCommand",
    "ContextCommand",
]
