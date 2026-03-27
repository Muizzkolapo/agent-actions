"""Shared base class for all inspect subcommands."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

from agent_actions.config.project_paths import (
    ProjectPaths,
    ProjectPathsFactory,
    find_config_file,
)
from agent_actions.errors import ConfigurationError
from agent_actions.models.action_schema import ActionSchema
from agent_actions.prompt.renderer import ConfigRenderingService
from agent_actions.workflow.coordinator import AgentWorkflow, WorkflowPaths, WorkflowRuntimeConfig

if TYPE_CHECKING:
    from agent_actions.workflow.schema_service import WorkflowSchemaService

logger = logging.getLogger(__name__)


class BaseInspectCommand:
    """Base class for inspect commands."""

    def __init__(self, agent: str, user_code: str | None, json_output: bool):
        self.agent = agent
        self.agent_name = Path(agent).stem
        self.user_code = user_code
        self.json_output = json_output
        self.console = Console()
        self.paths: ProjectPaths | None = None  # Will be set by _load_workflow
        self.schema_service: WorkflowSchemaService | None = None

    def _load_workflow(self, project_root: Path | None = None) -> AgentWorkflow:
        paths = ProjectPathsFactory.create_project_paths(
            self.agent_name, self.agent, auto_create=False, project_root=project_root
        )
        self.paths = paths
        filename = f"{self.agent_name}.yml"
        full_path = find_config_file(
            self.agent_name, paths.agent_config_dir, filename, check_alternatives=True
        )

        ConfigRenderingService().render_and_load_config(
            self.agent_name, full_path, paths.template_dir, project_root=project_root
        )

        workflow = AgentWorkflow(
            WorkflowRuntimeConfig(
                paths=WorkflowPaths(
                    constructor_path=str(full_path),
                    user_code_path=str(self.user_code) if self.user_code else None,
                    default_path=str(paths.default_config_path),
                ),
                use_tools=False,
                project_root=project_root,
            )
        )

        # Reuse schema service built during static validation
        self.schema_service = workflow.schema_service

        return workflow

    def _get_action_schema(self, action_name: str) -> ActionSchema | None:
        """Get ActionSchema for an action via the schema service."""
        if self.schema_service is None:
            return None
        return self.schema_service.get_action_schema(action_name)

    def _analyze_dependencies(self, workflow: AgentWorkflow) -> dict[str, Any]:
        from agent_actions.prompt.context.scope_inference import infer_dependencies

        workflow_actions = list(workflow.action_configs.keys())
        result = {}

        for action_name, action_config in workflow.action_configs.items():
            deps_raw = action_config.get("dependencies", [])
            if isinstance(deps_raw, str):
                explicit_deps = [deps_raw]
            elif isinstance(deps_raw, list):
                explicit_deps = deps_raw
            else:
                explicit_deps = []

            try:
                input_sources, context_sources = infer_dependencies(
                    action_config, workflow_actions, action_name
                )
            except (ConfigurationError, KeyError, ValueError) as e:
                if not self.json_output:
                    self.console.print(
                        f"[dim]Warning: Could not infer dependencies for {action_name}: {e}[/dim]"
                    )
                input_sources = explicit_deps
                context_sources = []

            context_scope = action_config.get("context_scope", {})
            has_primary_dep = "primary_dependency" in action_config

            result[action_name] = {
                "explicit_dependencies": explicit_deps,
                "input_sources": input_sources,
                "context_sources": context_sources,
                "context_scope": {
                    "observe": context_scope.get("observe", []),
                    "passthrough": context_scope.get("passthrough", []),
                },
                "has_primary_dependency": has_primary_dep,
                "primary_dependency": action_config.get("primary_dependency"),
            }

        return result

    @staticmethod
    def _get_action_type(input_sources: list[str], context_sources: list[str]) -> str:
        if not input_sources:
            return "Source"
        if len(input_sources) > 1:
            return "Merge" if not context_sources else "Merge + Context"
        return "Transform" if not context_sources else "Transform + Context"

    @staticmethod
    def _get_output_fields(
        action_config: dict[str, Any],
        action_schema: ActionSchema | None = None,
    ) -> list[str]:
        # Preferred: use pre-resolved ActionSchema from WorkflowSchemaService
        if action_schema is not None:
            return action_schema.available_outputs

        # Fallback for inline schema dicts (not file-based)
        schema = action_config.get("schema", {})
        if schema and isinstance(schema, dict):
            if "properties" in schema:
                return list(schema["properties"].keys())
            return list(schema.keys())

        # If schema_name is set but no ActionSchema resolved it, show placeholder
        schema_name = action_config.get("schema_name")
        if schema_name:
            return [f"[schema: {schema_name}]"]

        return []

    @staticmethod
    def _get_input_fields(action_config: dict[str, Any]) -> list[str]:
        fields = []
        ctx = action_config.get("context_scope", {})
        for field_ref in ctx.get("observe", []):
            fields.append(f"{field_ref} (observe)")
        for field_ref in ctx.get("passthrough", []):
            fields.append(f"{field_ref} (passthrough)")
        return fields
