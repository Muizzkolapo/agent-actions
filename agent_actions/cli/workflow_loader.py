"""Shared workflow loading utility for CLI commands.

Provides a single function to initialize an AgentWorkflow from project
paths, avoiding duplicate config loading / rendering across commands.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from agent_actions.config.project_paths import ProjectPaths
    from agent_actions.workflow.coordinator import AgentWorkflow


def validate_action_exists(action_name: str, action_configs: Mapping[str, Any]) -> None:
    """Raise ClickException if action_name is not in action_configs."""
    if action_name not in action_configs:
        available = ", ".join(sorted(action_configs.keys()))
        raise click.ClickException(f"Action '{action_name}' not found. Available: {available}")


def load_workflow(
    agent_name: str,
    paths: ProjectPaths,
    project_root: Path | None = None,
    *,
    user_code_path: str | None = None,
    use_tools: bool = False,
    fresh: bool = False,
    verify_keys: bool = False,
    upstream_scope: list[str] | None = None,
) -> AgentWorkflow:
    """Load and return an initialized AgentWorkflow.

    Handles config file resolution, template rendering, and workflow
    construction.  Callers can access ``workflow.execution_order``,
    ``workflow.run()``, etc. on the returned object.
    """
    from agent_actions.config.project_paths import find_config_file
    from agent_actions.prompt.renderer import ConfigRenderingService
    from agent_actions.workflow.coordinator import AgentWorkflow
    from agent_actions.workflow.models import WorkflowPaths, WorkflowRuntimeConfig

    filename = f"{agent_name}.yml"
    full_path = find_config_file(
        agent_name,
        paths.agent_config_dir,
        filename,
        check_alternatives=True,
        project_root=project_root,
    )
    ConfigRenderingService().render_and_load_config(
        agent_name,
        full_path,
        paths.template_dir,
        paths.rendered_workflows_dir,
        project_root=project_root,
    )
    return AgentWorkflow(
        WorkflowRuntimeConfig(
            paths=WorkflowPaths(
                constructor_path=str(full_path),
                user_code_path=user_code_path,
                default_path=str(paths.default_config_path),
            ),
            use_tools=use_tools,
            fresh=fresh,
            verify_keys=verify_keys,
            project_root=project_root,
            upstream_scope=upstream_scope,
        )
    )
