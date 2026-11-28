"""Shared workflow loading utility for CLI commands.

Provides a single function to initialize an AgentWorkflow from project
paths, avoiding duplicate config loading / rendering across commands.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from agent_actions.config.project_paths import ProjectPaths
    from agent_actions.workflow.coordinator import AgentWorkflow


def load_workflow(
    agent_name: str,
    paths: ProjectPaths,
    project_root: Path | None = None,
    *,
    sends_requests: bool,
    user_code_path: str | None = None,
    use_tools: bool = False,
    fresh: bool = False,
    rerun: Sequence[str] = (),
    verify_keys: bool = False,
    read_only: bool = False,
    record_limit: int | None = None,
    file_limit: int | None = None,
) -> AgentWorkflow:
    """Render the workflow config and construct an AgentWorkflow from it.

    A render error carries the workflow name, the config file's stem, as ``agent``.

    ``read_only`` skips the startup reset, which clears the state a read command reads.
    ``sends_requests=False`` makes an absent credential a warning instead of an error.
    """
    from agent_actions.config.project_paths import find_config_file
    from agent_actions.errors.base import AgentActionsError, enrich_exception_context
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
    try:
        rendered_workflow = ConfigRenderingService().render_and_load_config(
            agent_name,
            full_path,
            paths.template_dir,
            paths.rendered_workflows_dir,
            project_root=project_root,
        )
    except AgentActionsError as e:
        enrich_exception_context(e, agent=full_path.stem)
        raise
    workflow = AgentWorkflow(
        WorkflowRuntimeConfig(
            paths=WorkflowPaths(
                constructor_path=str(full_path),
                user_code_path=user_code_path,
                default_path=str(paths.default_config_path),
            ),
            use_tools=use_tools,
            fresh=fresh,
            rerun=tuple(rerun),
            verify_keys=verify_keys,
            sends_requests=sends_requests,
            project_root=project_root,
            record_limit=record_limit,
            file_limit=file_limit,
            rendered_workflow=rendered_workflow,
        ),
        read_only=read_only,
    )
    if sends_requests:
        _build_knowledge_indexes(workflow.action_configs, project_root)
    return workflow


def _build_knowledge_indexes(action_configs: Mapping[str, Any], project_root: Path | None) -> None:
    """Build the knowledge indexes the workflow's retrieve steps search, once per run."""
    from agent_actions.config import sandbox
    from agent_actions.config.path_config import resolve_project_root
    from agent_actions.llm.providers.tools.builtin import resolve_knowledge

    resolve_knowledge(action_configs, resolve_project_root(project_root), sandbox.is_active())


def validate_action_exists(action_name: str, action_configs: Mapping[str, Any]) -> None:
    """Raise ClickException if *action_name* is not in *action_configs*."""
    if action_name not in action_configs:
        available = ", ".join(action_configs.keys())
        raise click.ClickException(f"Action '{action_name}' not found. Available: {available}")
