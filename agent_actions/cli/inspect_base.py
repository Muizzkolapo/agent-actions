"""Shared base class for all inspect subcommands."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.text import Text

from agent_actions.config.project_paths import ProjectPaths
from agent_actions.errors import ConfigurationError
from agent_actions.models.action_schema import ActionSchema
from agent_actions.services.workflow_inspector import WorkflowInspector

if TYPE_CHECKING:
    from agent_actions.workflow.schema_service import WorkflowSchemaService

logger = logging.getLogger(__name__)


def render_title_row(
    console: Console,
    subject: str,
    *,
    section: str | None = None,
    validated: bool = False,
    graph_hash: str | None = None,
) -> None:
    """Shared title-row renderer for every `agac inspect` command.

    Format:  `<subject>   <suffix>` left-aligned with no leading
    indent; optional graph-hash flushed right.

    The suffix is exactly one of:
      - a status pill (` ● validated `, mint-on-darker-mint) when
        ``validated=True``
      - a dim section label (e.g. ``dependency model``) when
        ``section`` is given
      - nothing

    Standardising this keeps the visual language consistent across
    the inspect family.
    """
    width = console.width or 100
    left = Text()
    left.append(subject, style="bold bright_white")
    if validated:
        left.append("   ")
        left.append("● validated", style="bold black on rgb(108,168,138)")
    elif section:
        left.append("   ")
        left.append(section, style="dim")

    if graph_hash:
        right = Text("graph hash ", style="dim")
        right.append(graph_hash, style="dim bright_white")
        pad = max(width - left.cell_len - right.cell_len, 2)
        line = Text()
        line.append(left)
        line.append(" " * pad)
        line.append(right)
        console.print(line)
    else:
        console.print(left)


def compute_graph_hash(action_configs: dict) -> str:
    """Short, stable identifier — same configs always hash the same.

    Hash of action names + their direct deps. Display as `XXXX·XXXX`
    like a short git SHA, gives the user something to recognise.
    """
    import hashlib

    payload_parts = []
    for name in sorted(action_configs):
        deps = action_configs[name].get("dependencies") or []
        if isinstance(deps, str):
            deps = [deps]
        payload_parts.append(f"{name}:{','.join(sorted(deps))}")
    digest = hashlib.sha256("|".join(payload_parts).encode()).hexdigest()
    return f"{digest[:4]}·{digest[4:8]}"


class BaseInspectCommand:
    """Base class for inspect commands."""

    def __init__(self, agent: str, user_code: str | None, json_output: bool):
        self.agent = agent
        self.agent_name = Path(agent).stem
        self.user_code = user_code
        self.json_output = json_output
        self.console = Console()
        self.paths: ProjectPaths | None = None
        self.schema_service: WorkflowSchemaService | None = None

    def _load_inspector(self, project_root: Path | None = None) -> WorkflowInspector:
        """Load a workflow inspector for read-only introspection.

        Does NOT initialize the storage backend or runtime execution
        services — that overhead is wasted on read-only commands.
        Validation still runs so the inspect commands surface the same
        errors ``agac run`` would surface, but bypasses key probing
        (``verify_keys=False``) since introspection shouldn't make
        network calls.
        """
        inspector = WorkflowInspector(
            agent_name=self.agent_name,
            project_root=project_root,
            user_code_path=self.user_code,
        )
        # validate() runs load() internally and populates schema_service.
        # The inspect subcommands need schema_service for output-field
        # resolution, so we always validate here.
        inspector.validate(verify_keys=False)
        self.paths = inspector.paths
        self.schema_service = inspector.schema_service
        return inspector

    def _get_action_schema(self, action_name: str) -> ActionSchema | None:
        """Get ActionSchema for an action via the schema service."""
        if self.schema_service is None:
            return None
        return self.schema_service.get_action_schema(action_name)

    def _analyze_dependencies(self, inspector: WorkflowInspector) -> dict[str, Any]:
        from agent_actions.prompt.context.scope_inference import infer_dependencies

        workflow_actions = list(inspector.action_configs.keys())
        result = {}

        for action_name, action_config in inspector.action_configs.items():
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
                    "drop": context_scope.get("drop", []),
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
        for field_ref in ctx.get("drop", []):
            fields.append(f"{field_ref} (drop)")
        return fields
