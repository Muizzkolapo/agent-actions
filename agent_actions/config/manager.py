"""Module for Configuration Validation Functions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import ValidationError

from agent_actions.config.environment import EnvironmentConfig
from agent_actions.config.path_config import (
    find_project_root_dir,
    load_project_config,
    resolve_project_root,
)
from agent_actions.config.paths import PathManager, ProjectRootNotFoundError
from agent_actions.config.schema import WorkflowConfig
from agent_actions.errors import ConfigurationError, ConfigValidationError, TemplateRenderingError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import ConfigLoadEvent, ConfigLoadStartEvent
from agent_actions.output.response.config_fields import get_default

if TYPE_CHECKING:
    from agent_actions.output.response.config_schema import AgentConfig

logger = logging.getLogger(__name__)


class ConfigManager:
    def __init__(self, constructor_path: str, default_path: str, project_root: Path | None = None):
        self.constructor_path = constructor_path
        self.default_path = default_path
        self.project_root = project_root
        self.user_config: dict[str, Any] | None = None
        self.default_config: dict[str, Any] | None = None
        self.agent_name: str | None = None
        self.agent_configs: dict[str, AgentConfig] = {}
        self.execution_order: list[str] = []
        self.child_pipeline: str | None = None
        self.tool_path: list[str] | None = None
        self.template_dir = str(resolve_project_root(project_root) / "templates")
        self.environment_config: EnvironmentConfig | None = None
        self.workflow_config: Any = None
        self.pipeline_config: Any = None

    def _load_single_config(self, config_path: str, config_type: str) -> dict[str, Any]:
        """Load and parse a single config file with template rendering.

        Args:
            config_path: Path to the config file.
            config_type: Human-readable config type for events/errors (e.g. "workflow", "default").

        Returns:
            Parsed config dictionary.

        Raises:
            ConfigurationError: On rendering, YAML parsing, or unexpected errors.
        """
        from agent_actions.prompt.render_workflow import render_pipeline_with_templates

        fire_event(ConfigLoadStartEvent(config_file=str(config_path)))
        try:
            config_data = render_pipeline_with_templates(
                config_path, self.template_dir, project_root=self.project_root
            )
            loaded: dict[str, Any] = yaml.safe_load(config_data)
            fire_event(ConfigLoadEvent(config_file=str(config_path), config_type=config_type))
            return loaded
        except TemplateRenderingError as e:
            config_name = Path(config_path).name
            raise ConfigurationError(
                f"Jinja2 template error in {config_type} config '{config_name}': {e}",
                context={
                    "config_path": str(config_path),
                    "operation": "template_rendering",
                },
                cause=e,
            ) from e
        except ConfigurationError:
            raise
        except yaml.YAMLError as e:
            config_name = Path(config_path).name
            raise ConfigurationError(
                f"Invalid YAML in {config_type} config '{config_name}': {e}",
                context={"config_path": str(config_path), "operation": "parse_yaml"},
                cause=e,
            ) from e
        except Exception as e:
            config_name = Path(config_path).name
            raise ConfigurationError(
                f"Failed to load {config_type} config '{config_name}': {type(e).__name__}: {e}",
                context={
                    "config_path": str(config_path),
                    "operation": f"load_{config_type}_config",
                },
                cause=e,
            ) from e

    def load_configs(self):
        self.user_config = self._load_single_config(self.constructor_path, "workflow")
        if self.default_path:
            self.default_config = self._load_single_config(self.default_path, "default")
        # Resolve tool_path with priority: workflow > default > project config
        user_tool_path = None
        if isinstance(self.user_config, dict):
            user_tool_path = self.user_config.get("tool_path")
        default_tool_path = None
        if isinstance(self.default_config, dict):
            default_tool_path = self.default_config.get("tool_path")

        # Also check project config (agent_actions.yml) as fallback
        project_tool_path = None
        try:
            path_manager = PathManager(project_root=self.project_root)
            project_root = path_manager.get_project_root()
            project_config = load_project_config(project_root)
            project_tool_path = project_config.get("tool_path")
        except (OSError, yaml.YAMLError, KeyError, TypeError, AttributeError) as e:
            logger.debug("Could not resolve tool_path from project config: %s", e)

        # Priority: workflow config > default config > project config
        # Normalize to list[str] so downstream iteration is always safe.
        raw = user_tool_path or default_tool_path or project_tool_path
        if raw is not None:
            self.tool_path = [raw] if isinstance(raw, str) else list(raw)
        else:
            self.tool_path = ["tools"]
            logger.warning("No tool_path configured; defaulting to 'tools/'")

    def find_agent_name(self, config: dict[str, Any]) -> str:
        """
        Find the name of the agent from the configuration.

        Args:
            config: Agent configuration dictionary

        Returns:
            str: Name of the agent
        """
        if "name" in config and "actions" in config:
            return str(config["name"])
        if not config:
            raise ConfigurationError(
                "Cannot find agent name: configuration is empty",
                context={"config_keys": list(config.keys())},
            )
        return str(next(iter(config)))

    def validate_agent_name(self) -> None:
        if self.user_config is None:
            raise RuntimeError(
                "user_config is None: load_configs() must be called before validate_agent_name()"
            )
        self.agent_name = self.find_agent_name(self.user_config)
        config_filename = Path(self.constructor_path).stem
        if self.agent_name != config_filename:
            raise ConfigurationError(
                "Top-level key does not match the filename",
                context={
                    "agent_name": self.agent_name,
                    "config_filename": config_filename,
                    "operation": "validate_agent_name",
                },
            )

    def check_child_pipeline(self) -> None:
        if self.user_config is None:
            raise RuntimeError(
                "user_config is None: load_configs() must be called before check_child_pipeline()"
            )
        if "name" in self.user_config and "actions" in self.user_config:
            actions = self.user_config.get("actions", [])
            for action in actions:
                if isinstance(action, dict) and "child" in action:
                    if not action["child"]:
                        continue
                    self.child_pipeline = action["child"][0]
                    return
        else:
            if self.agent_name is None:
                raise RuntimeError(
                    "agent_name is None: validate_agent_name() must be called "
                    "before check_child_pipeline()"
                )
            agent_list = self.user_config.get(self.agent_name, [])
            for item in agent_list:
                if isinstance(item, dict) and "child" in item:
                    if not item["child"]:
                        continue
                    self.child_pipeline = item["child"][0]
                    return
        self.child_pipeline = None

    def get_user_agents(self) -> list[dict[str, Any]]:
        from agent_actions.output.response.expander import ActionExpander

        if self.user_config is None:
            raise RuntimeError(
                "user_config is None: load_configs() must be called before get_user_agents()"
            )
        if "name" in self.user_config and "actions" in self.user_config:
            try:
                path_manager = PathManager(project_root=self.project_root)
                project_root = path_manager.get_project_root()
                project_config = load_project_config(project_root)
                project_defaults = project_config.get("default_agent_config", {})
            except (FileNotFoundError, ProjectRootNotFoundError):
                project_defaults = {}
            except (yaml.YAMLError, OSError, ConfigValidationError) as e:
                raise ConfigurationError(
                    "Failed to load project defaults",
                    context={
                        "config_path": str(self.constructor_path),
                        "operation": "load_project_defaults",
                    },
                    cause=e,
                ) from e
            # Validate entire workflow config (actions, defaults, duplicates,
            # dangling deps, circular deps) in one pass via Pydantic.
            try:
                workflow = WorkflowConfig.model_validate(self.user_config)
            except ValidationError as e:
                raise ConfigurationError(
                    "Workflow configuration is invalid",
                    context={
                        "config_path": str(self.constructor_path),
                        "workflow_name": self.user_config.get("name", "unknown"),
                    },
                    cause=e,
                ) from e

            validated_actions = [
                action.model_dump(mode="python", exclude_unset=True, by_alias=True)
                for action in workflow.actions
            ]
            validated_defaults = (
                workflow.defaults.model_dump(mode="python", exclude_unset=True, by_alias=True)
                if workflow.defaults
                else {}
            )
            merged_defaults = {**project_defaults, **validated_defaults}
            workflow_name = workflow.name
            config_for_expander = {
                "name": workflow_name,
                "actions": validated_actions,
                "defaults": merged_defaults,
            }

            agent_config_map = ActionExpander.expand_actions_to_agents(config_for_expander)
            return agent_config_map.get(workflow_name, [])  # type: ignore[return-value]
        else:
            if self.agent_name is None:
                raise RuntimeError(
                    "agent_name is None: validate_agent_name() must be called "
                    "before get_user_agents()"
                )
            agents_section = self.user_config[self.agent_name]
            if "agents" in agents_section:
                return agents_section["agents"]  # type: ignore[no-any-return]
            return [
                agent
                for agent in agents_section
                if isinstance(agent, dict) and "agent_type" in agent
            ]

    def merge_agent_configs(self, user_agents: list[dict[str, Any]]) -> None:
        from agent_actions.output.response.config_schema import AgentConfig, DefaultAgentConfig

        default_model = DefaultAgentConfig.model_validate(
            self.default_config.get("default_agent_config", {}) if self.default_config else {}
        )
        default_agent_config = default_model.model_dump()
        for agent in user_agents:
            try:
                agent_model = AgentConfig.model_validate(agent)
            except ValidationError as e:
                raise ConfigurationError(
                    "Invalid agent configuration",
                    context={
                        "agent_type": agent.get("agent_type", "unknown"),
                        "operation": "merge_agent_configs",
                    },
                    cause=e,
                ) from e
            agent_type = agent_model.agent_type
            agent_dict = agent_model.model_dump(exclude_unset=True)
            merged_dict = {**default_agent_config}
            # Add root-level tool_path to agent config for dispatch_task() support
            if self.tool_path:
                merged_dict["tool_path"] = self.tool_path
            for key, value in agent_dict.items():
                if key == "chunk_config" and isinstance(value, dict):
                    default_chunk = merged_dict.get(key)
                    if not isinstance(default_chunk, dict):
                        default_chunk = {}
                    merged_dict[key] = {**default_chunk, **value}
                else:
                    merged_dict[key] = value
            merged_agent_config = AgentConfig.model_validate(merged_dict)
            self.agent_configs[agent_type] = merged_agent_config

    def determine_execution_order(self) -> None:
        """Determine execution order of agents based on their dependencies.

        Uses auto-inferred dependencies from context_scope to build the execution graph.
        Only considers is_operational agents.
        """
        from agent_actions.input.context.normalizer import normalize_all_agent_configs
        from agent_actions.output.response.config_schema import AgentConfig
        from agent_actions.prompt.context.scope_inference import infer_dependencies
        from agent_actions.utils.graph_utils import topological_sort

        workflow_actions = list(self.agent_configs.keys())

        dependency_graph = {}
        for agent_type, config in self.agent_configs.items():
            if config.is_operational:
                try:
                    input_sources, context_sources = infer_dependencies(
                        config.model_dump(), workflow_actions, agent_type
                    )
                    all_deps: list[Any] = input_sources + context_sources
                except Exception as e:
                    logger.warning(
                        "Dependency inference failed for %s, using explicit deps: %s",
                        agent_type,
                        e,
                        exc_info=True,
                    )
                    all_deps = list(config.dependencies)

                dependencies = [
                    dep
                    for dep in all_deps
                    if isinstance(dep, str)
                    and dep in self.agent_configs
                    and self.agent_configs[dep].is_operational
                ]
                dependency_graph[agent_type] = dependencies
        self.execution_order = topological_sort(dependency_graph)

        # Normalize context_scope for all agents (expands version references in-place)
        agent_configs_dict = {
            agent_type: config.model_dump() for agent_type, config in self.agent_configs.items()
        }
        normalize_all_agent_configs(agent_configs_dict, self.execution_order)

        for agent_type, config_dict in agent_configs_dict.items():
            self.agent_configs[agent_type] = AgentConfig.model_validate(config_dict)

    def load_environment_config(self) -> EnvironmentConfig:
        """Load and validate environment configuration."""
        try:
            env_file = self._resolve_dotenv()
            self.environment_config = EnvironmentConfig(_env_file=env_file)  # type: ignore[call-arg]
            return self.environment_config
        except ValidationError as e:
            raise ConfigurationError(
                "Invalid environment configuration",
                context={"operation": "load_environment_config"},
                cause=e,
            ) from e

    def _resolve_dotenv(self) -> Path | None:
        """Return the absolute path to ``.env`` at the project root, or ``None``."""
        root = self.project_root or find_project_root_dir()
        if root is None:
            return None
        env_path = Path(root) / ".env"
        return env_path if env_path.is_file() else None

    def get_agent_config(self, agent_type: str) -> AgentConfig | None:
        """Get typed agent configuration by agent type."""
        return self.agent_configs.get(agent_type)

    def get_all_agent_configs(self) -> dict[str, AgentConfig]:
        """Get all typed agent configurations."""
        return self.agent_configs.copy()

    def get_all_agent_configs_as_dicts(self) -> dict[str, dict[str, Any]]:
        """Get all agent configurations as dictionaries for backward compatibility."""
        result = {}
        for agent_type, config in self.agent_configs.items():
            config_dict = config.model_dump()

            # Required for LLM actions — fail fast instead of masking with "".
            # tool/hitl kinds get model_vendor overridden below, so skip them.
            kind = config_dict.get("kind")
            if kind not in ("tool", "hitl"):
                if not config_dict.get("model_vendor"):
                    raise ConfigurationError(
                        f"Action '{agent_type}' is missing required field 'model_vendor'",
                        context={"action": agent_type, "field": "model_vendor"},
                    )

            # Optional fields — default None → "" to satisfy downstream
            # string expectations (e.g., template rendering, empty conditionals).
            optional_string_defaults = {
                "conditional_clause": "",
                "granularity": get_default("granularity"),
                "run_mode": get_default("run_mode"),
                "prompt": "",
                "schema_name": "",
                "code_path": "",
                "anthropic_version": "",
            }
            for field, default_value in optional_string_defaults.items():
                if field in config_dict and config_dict[field] is None:
                    if default_value != "":
                        logger.debug(
                            "Config coercion: '%s' defaulting to '%s'",
                            field,
                            default_value,
                        )
                    config_dict[field] = default_value

            # Normalize kind to model_vendor for tool and hitl actions.
            # This intentionally overrides inherited/default vendors (e.g., openai)
            # so kind-specific actions always route to the correct client.
            if config_dict.get("kind") == "tool":
                config_dict["model_vendor"] = "tool"
            if config_dict.get("kind") == "hitl":
                config_dict["model_vendor"] = "hitl"

            result[agent_type] = config_dict
        return result

    def create_pipeline_config(self, pipeline_data: dict[str, Any]) -> Any:
        """Create a typed pipeline configuration from dictionary data."""
        from agent_actions.workflow.pipeline import PipelineConfig as _PipelineConfig

        try:
            self.pipeline_config = _PipelineConfig.model_validate(pipeline_data)  # type: ignore[attr-defined]
            return self.pipeline_config
        except ValidationError as e:
            raise ConfigurationError(
                "Invalid pipeline configuration",
                context={
                    "pipeline_name": pipeline_data.get("name", "unknown"),
                    "operation": "create_pipeline_config",
                },
                cause=e,
            ) from e

    def validate_all_configs(self) -> None:
        """Validate all loaded configurations."""
        from agent_actions.output.response.config_schema import AgentConfig

        if not self.environment_config:
            self.load_environment_config()
        for agent_type, config in self.agent_configs.items():
            try:
                AgentConfig.model_validate(config.model_dump())
            except ValidationError as e:
                raise ConfigurationError(
                    "Agent configuration is invalid",
                    context={"agent_type": agent_type, "operation": "validate_all_configs"},
                    cause=e,
                ) from e

    def get_configuration_summary(self) -> dict[str, Any]:
        """Get a summary of all loaded configurations."""
        project_name = None
        try:
            from agent_actions.config.path_config import get_project_name

            project_name = get_project_name(self.project_root)
        except (OSError, ConfigValidationError) as exc:
            logger.debug("Could not retrieve project_name for summary: %s", exc)

        return {
            "project": {
                "name": project_name,
            },
            "environment": {
                "loaded": self.environment_config is not None,
                "env": (
                    self.environment_config.agent_actions_env if self.environment_config else None
                ),
            },
            "agents": {
                "count": len(self.agent_configs),
                "types": list(self.agent_configs.keys()),
                "execution_order": self.execution_order,
            },
            "workflow": {
                "loaded": self.workflow_config is not None,
                "name": getattr(self.workflow_config, "name", None),
            },
            "pipeline": {
                "loaded": self.pipeline_config is not None,
                "name": getattr(self.pipeline_config, "name", None),
            },
        }
