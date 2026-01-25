"""Navigation utilities for Agent Actions LSP."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from .models import ProjectIndex


@dataclass
class ActionGraph:
    """Graph representation for workflow actions."""

    action: str
    dependencies: List[str]
    consumers: List[str]


def build_action_graph(index: ProjectIndex, workflow_file: Path) -> Dict[str, ActionGraph]:
    """Build an action dependency graph for a workflow file."""
    actions = index.file_actions.get(workflow_file, {})
    consumers: Dict[str, List[str]] = {name: [] for name in actions}

    for action in actions.values():
        for dependency in action.dependencies:
            if dependency in consumers:
                consumers[dependency].append(action.name)

    graph = {}
    for name, action in actions.items():
        graph[name] = ActionGraph(
            action=name,
            dependencies=action.dependencies,
            consumers=consumers.get(name, []),
        )

    return graph


def describe_action_relationships(
    index: ProjectIndex, workflow_file: Path, action_name: str
) -> ActionGraph | None:
    """Return dependencies and consumers for a specific action."""
    graph = build_action_graph(index, workflow_file)
    return graph.get(action_name)
