"""Lightweight workflow inspector for read-only introspection.

Renders, validates, and resolves a workflow without initializing the
storage backend or runtime execution services. Used by the
``agac inspect`` subcommands.

Exposes ``action_configs``, ``execution_order``, and ``schema_service``
(populated after ``validate()``) so call sites can treat it as a
read-only view of the workflow.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

from agent_actions.config.manager import ConfigManager
from agent_actions.config.project_paths import (
    ProjectPaths,
    ProjectPathsFactory,
    find_config_file,
)
from agent_actions.prompt.renderer import ConfigRenderingService
from agent_actions.services.preflight_service import PreflightService
from agent_actions.workflow.config_pipeline import discover_workflow_udfs
from agent_actions.workflow.models import WorkflowPaths, WorkflowRuntimeConfig
from agent_actions.workflow.schema_service import WorkflowSchemaService

logger = logging.getLogger(__name__)


class WorkflowInspector:
    """Lightweight workflow introspection.

    No storage backend, no execution services, no LLM calls.

    Drives the same ``ConfigManager`` pipeline the runtime uses, so
    ``action_configs`` and ``execution_order`` reflect what the runtime
    would actually execute. UDF discovery fires its normal start/complete
    events; the runtime initialization event is intentionally skipped.
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
        # Resolve config file once so render() and load() agree.
        self._config_path = find_config_file(
            agent_name,
            self.paths.agent_config_dir,
            f"{agent_name}.yml",
            check_alternatives=True,
            project_root=project_root,
        )
        # Populated by load() / validate().
        self.action_configs: dict[str, dict[str, Any]] = {}
        self.execution_order: list[str] = []
        self.schema_service: WorkflowSchemaService | None = None
        self._loaded = False

    @property
    def config_path(self) -> Path:
        """Path to the agent's constructor (workflow) config file."""
        return self._config_path

    def render(self) -> str:
        """Return the fully rendered workflow YAML.

        Output reflects template expansion, prompt resolution, schema
        inlining, and version expansion. It does NOT apply runtime-only
        transforms such as guard-nullable schema fixes — those are
        layered on by the runtime, not the renderer.
        """
        action_config_map = ConfigRenderingService().render_and_load_config(
            self.agent_name,
            self._config_path,
            self.paths.template_dir,
            self.paths.rendered_workflows_dir,
            project_root=self.project_root,
        )
        # New-format configs land under "_validated_actions"; legacy
        # configs land under the agent_name top-level key.
        actions = action_config_map.get("_validated_actions") or action_config_map.get(
            self.agent_name, []
        )
        workflow_dict = {
            "name": self.agent_name,
            "actions": actions,
        }
        return yaml.dump(workflow_dict, sort_keys=False)

    def load(self) -> dict[str, dict[str, Any]]:
        """Run the config pipeline and populate ``action_configs`` +
        ``execution_order``. Idempotent.

        Skips the runtime initialization event but UDF-discovery events
        still fire (shared helper).
        """
        if self._loaded:
            return self.action_configs

        manager = ConfigManager(
            str(self._config_path),
            str(self.paths.default_config_path),
            project_root=self.project_root,
        )
        manager.load_configs()
        manager.validate_agent_name()

        # UDF discovery is read-only (scans filesystem, populates a
        # process-level registry). Route its banners to stderr so they
        # stay visible to the user without polluting stdout (which
        # carries the JSON / rendered YAML payload).
        quiet_console = Console(stderr=True)
        runtime_config = WorkflowRuntimeConfig(
            paths=WorkflowPaths(
                constructor_path=str(self._config_path),
                user_code_path=self.user_code_path,
                default_path=str(self.paths.default_config_path),
            ),
            use_tools=False,
            manager=manager,
            project_root=self.project_root,
        )
        discover_workflow_udfs(runtime_config, quiet_console)

        user_agents = manager.get_user_agents()
        manager.merge_agent_configs(user_agents)
        manager.determine_execution_order()

        self.action_configs = manager.get_all_agent_configs_as_dicts()
        self.execution_order = list(manager.execution_order)
        self._loaded = True
        return self.action_configs

    def validate(self, verify_keys: bool = False) -> None:
        """Run preflight validation. Raises ``PreFlightValidationError``
        on failure. Side-effect: populates ``self.schema_service``.
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

    def get_levels(self) -> list[list[str]]:
        """Group actions into execution levels (parallelizable groups)
        respecting ``depends_on``/``dependencies``.

        Returns one list per topological level. Empty when the workflow
        has no actions.
        """
        self.load()
        if not self.action_configs:
            return []

        def _deps_of(config: dict[str, Any]) -> list[str]:
            deps = config.get("depends_on")
            if deps is None:
                deps = config.get("dependencies", [])
            if isinstance(deps, str):
                return [deps]
            return list(deps or [])

        # execution_order only covers operational agents — non-operational
        # ones are absent. Use it as the preferred order, then append any
        # action_configs entries it missed so we don't drop them or
        # mis-attribute them as a dependency cycle.
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
                # Cycle or unresolved dependency — dump the rest in one
                # bucket so callers can still display something.
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
