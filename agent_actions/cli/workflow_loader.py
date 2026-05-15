"""Shared workflow loading utility for CLI commands.

Provides a single function to initialize an AgentWorkflow from project
paths, avoiding duplicate config loading / rendering across commands.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_actions.config.project_paths import ProjectPaths


def load_workflow(
    agent_name: str,
    paths: ProjectPaths,
    project_root: Path | None = None,
):
    """Load and return an initialized AgentWorkflow.

    Handles config file resolution, template rendering, and workflow
    construction.  Callers can access ``workflow.execution_order``,
    ``workflow.run()``, etc. on the returned object.
    """
    from agent_actions.config.loader import find_config_file
    from agent_actions.config.rendering import ConfigRenderingService
    from agent_actions.workflow.coordinator import AgentWorkflow
    from agent_actions.workflow.runtime_config import WorkflowPaths, WorkflowRuntimeConfig

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
                default_path=str(paths.default_config_path),
            ),
            project_root=project_root,
        )
    )
