"""Read-only workflow introspection for ``agac inspect``.

Exposes ``action_configs``, ``execution_order``, and ``schema_service``
without spinning up storage or runtime services.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from rich.console import Console

from agent_actions.config.project_paths import (
    ProjectPaths,
    ProjectPathsFactory,
    find_config_file,
)
from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.services.preflight_service import PreflightService
from agent_actions.workflow.config_pipeline import load_workflow_configs
from agent_actions.workflow.context_scope_pruning import strip_unreachable_drops
from agent_actions.workflow.models import WorkflowPaths, WorkflowRuntimeConfig
from agent_actions.workflow.schema_service import WorkflowSchemaService

logger = logging.getLogger(__name__)


class WorkflowInspector:
    """Read-only workflow introspection.

    ``load()`` delegates to the runtime's ``load_workflow_configs`` so
    inspect output matches what ``agac run`` would actually see, but
    with workflow-init and UDF-discovery events suppressed.
    """

    def __init__(
        self,
        agent_name: str,
        project_root: Path | None = None,
        user_code_path: str | None = None,
    ):
        self.agent_name = agent_name
        self.project_root = project_root
        self.user_code_path = user_code_path
        self.paths: ProjectPaths = ProjectPathsFactory.create_project_paths(
            agent_name, agent_name, auto_create=False, project_root=project_root
        )
        self._config_path = find_config_file(
            agent_name,
            self.paths.agent_config_dir,
            f"{agent_name}.yml",
            check_alternatives=True,
            project_root=project_root,
        )
        self.action_configs: dict[str, dict[str, Any]] = {}
        self.execution_order: list[str] = []
        self.schema_service: WorkflowSchemaService | None = None
        self._loaded = False

    @property
    def config_path(self) -> Path:
        return self._config_path

    def render(self) -> str:
        """Return the fully rendered workflow YAML.

        Every top-level key in the source YAML survives. Runtime
        mutations (drop pruning, guard-nullable schema fixes) are NOT
        applied — ``--yaml`` is the pre-preflight snapshot.
        """
        return render_pipeline_with_templates(
            self._config_path,
            self.paths.template_dir,
            project_root=self.project_root,
        )

    def load(self) -> dict[str, dict[str, Any]]:
        """Populate ``action_configs`` and ``execution_order``. Idempotent."""
        if self._loaded:
            return self.action_configs

        # UDF banners on stderr keep stdout clean for JSON/YAML payloads.
        quiet_console = Console(stderr=True)
        runtime_config = WorkflowRuntimeConfig(
            paths=WorkflowPaths(
                constructor_path=str(self._config_path),
                user_code_path=self.user_code_path,
                default_path=str(self.paths.default_config_path),
            ),
            use_tools=False,
            project_root=self.project_root,
        )

        metadata = load_workflow_configs(runtime_config, quiet_console, fire_events=False)

        self.action_configs = metadata.action_configs
        self.execution_order = list(metadata.execution_order)
        self._loaded = True
        return self.action_configs

    def validate(self, verify_keys: bool = False) -> None:
        """Run preflight, populate ``schema_service``, strip dead drops.

        Drop-pruning mirrors the coordinator so ``--dry-run`` reports the
        same post-preflight state ``agac run`` will see. Raises
        ``PreFlightValidationError`` on failure.
        """
        self.load()
        service = PreflightService(
            agent_name=self.agent_name,
            action_configs=self.action_configs,
            project_root=self.project_root,
            workflow_config_path=str(self._config_path),
            verify_keys=verify_keys,
        )
        service.validate()
        self.schema_service = service.schema_service
        strip_unreachable_drops(self.action_configs)

    def get_levels(self) -> list[list[str]]:
        """Topological levels of parallelizable actions."""
        self.load()
        if not self.action_configs:
            return []

        def _deps_of(config: dict[str, Any]) -> list[str]:
            # `or` (not `is None`) so depends_on:[] defers to dependencies —
            # matches scope_inference / workflow_static_analyzer.
            deps = config.get("depends_on") or config.get("dependencies") or []
            if isinstance(deps, str):
                return [deps]
            return list(deps)

        # execution_order skips non-operational agents — append them at
        # the tail so they still get bucketed instead of looking like a cycle.
        operational = [name for name in self.execution_order if name in self.action_configs]
        remaining = operational + [name for name in self.action_configs if name not in operational]
        completed: set[str] = set()
        levels: list[list[str]] = []

        while remaining:
            level = [
                name
                for name in remaining
                if all(d in completed for d in _deps_of(self.action_configs[name]))
            ]
            if not level:
                # Cycle / unresolved dep — dump the rest so callers still see something.
                levels.append(list(remaining))
                break
            levels.append(level)
            completed.update(level)
            remaining = [name for name in remaining if name not in completed]

        return levels

    def get_context_scope(self) -> dict[str, dict[str, Any]]:
        """Return per-action context_scope summary for ``--dry-run``."""
        self.load()
        result: dict[str, dict[str, Any]] = {}
        for name, config in self.action_configs.items():
            scope = config.get("context_scope", {}) or {}
            if isinstance(scope, str):
                summary: Any = scope
            else:
                summary = {
                    "observe": list(scope.get("observe", []) or []),
                    "passthrough": list(scope.get("passthrough", []) or []),
                    "drop": list(scope.get("drop", []) or []),
                }
            result[name] = {"scope": summary}
        return result

    def estimate(self) -> dict[str, Any]:
        """Estimate resource shape without executing any LLM calls."""
        self.load()
        llm_kinds = {"llm", "prompt"}
        llm_actions = [
            name
            for name, config in self.action_configs.items()
            if config.get("kind", "llm") in llm_kinds
        ]
        guarded_actions = [
            name for name, config in self.action_configs.items() if config.get("guard")
        ]
        return {
            "action_count": len(self.action_configs),
            "llm_calls": len(llm_actions),
            "guarded_actions": len(guarded_actions),
        }
