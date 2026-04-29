"""Configuration rendering service for templates and config data."""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import ValidationError
from yaml import YAMLError

from agent_actions.config.path_config import get_schema_path
from agent_actions.config.types import ActionConfigMap, ActionEntryDict
from agent_actions.errors import ConfigurationError, ConfigValidationError
from agent_actions.output.response.config_fields import get_default
from agent_actions.output.response.config_schema import AgentConfig
from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.utils.error_handler import ErrorHandler
from agent_actions.utils.error_wrap import as_validation_error
from agent_actions.utils.path_utils import resolve_relative_to
from agent_actions.utils.project_root import find_project_root
from agent_actions.validation.config_validator import ConfigValidator
from agent_actions.validation.path_validator import PathValidator
from agent_actions.validation.schema_validator import SchemaValidator

logger = logging.getLogger(__name__)


class TemplateRenderer(ABC):
    """Abstract interface for template rendering."""

    @abstractmethod
    def render(
        self,
        config_path: str,
        template_dir: str,
        output_path: str | None = None,
        project_root: Path | None = None,
    ) -> str:
        """
        Render a template with the given configuration.

        Args:
            config_path: Path to the configuration file.
            template_dir: Path to the template directory.
            output_path: Optional path to save the rendered output.
            project_root: Optional project root for resolving relative paths.

        Returns:
            Rendered template as a string.

        Raises:
            TemplateRenderingError: If rendering fails.
        """


class JinjaTemplateRenderer(TemplateRenderer):
    """Template renderer implementation using Jinja."""

    def render(
        self,
        config_path: str,
        template_dir: str,
        output_path: str | None = None,
        project_root: Path | None = None,
    ) -> str:
        """
        Render a template with the given configuration using Jinja.

        Args:
            config_path: Path to the configuration file (as string).
            template_dir: Path to the template directory (as string).
            output_path: Optional path to save the rendered output
                (as string, can be a directory path).
            project_root: Optional project root for resolving relative paths.

        Returns:
            Rendered template as a string.

        Raises:
            ValueError: If input validation fails
                (caught by the generic handler).
            Any exception from render_pipeline_with_templates or
                ErrorHandler.
        """
        try:
            logger.info(
                "Starting render template",
                extra={
                    "operation": "render template",
                    "config_path": config_path,
                    "template_dir": template_dir,
                    "output_path": output_path,
                },
            )
            path_validator = PathValidator()
            all_validations_passed = True
            error_messages: list[str] = []
            data_config_file = {
                "operation": "validate_file",
                "path": Path(config_path),
                "path_name": "Configuration file",
                "required": True,
                "must_be_readable": True,
            }
            if not path_validator.validate(data_config_file):
                all_validations_passed = False
                error_messages.extend(path_validator.get_errors())
            data_template_dir = {
                "operation": "validate_directory",
                "path": Path(template_dir),
                "path_name": "Template directory",
                "required": True,
                "must_be_readable": True,
            }
            if not path_validator.validate(data_template_dir):
                all_validations_passed = False
                error_messages.extend(path_validator.get_errors())
            output_file_to_write: str | None = None
            if output_path:
                output_dir_as_path = Path(output_path)
                data_output_dir = {
                    "operation": "ensure_directory_exists",
                    "path": output_dir_as_path,
                    "path_name": "Output directory",
                    "create_if_missing": True,
                    "must_be_writable_after_creation": True,
                }
                if not path_validator.validate(data_output_dir):
                    all_validations_passed = False
                    error_messages.extend(path_validator.get_errors())
                else:
                    config_name_stem = Path(config_path).stem
                    output_file_to_write = str(output_dir_as_path / f"{config_name_stem}.yml")
            else:
                logger.info("No output path provided; template will be rendered to memory/stdout.")
            if not all_validations_passed:
                error_prefix = "Input validation failed for template rendering: \n"
                formatted_errors = "\n".join(f"- {msg}" for msg in error_messages)
                final_error_message = error_prefix + formatted_errors
                raise ValueError(final_error_message)
            logger.info("All path validations passed. Proceeding to render template.")
            rendered_template = render_pipeline_with_templates(
                config_path, template_dir, project_root=project_root
            )
            if output_file_to_write:
                with open(output_file_to_write, "w", encoding="utf-8") as f:
                    f.write(rendered_template)
                logger.info("Rendered template saved to: %s", output_file_to_write)
            logger.info(
                "Successfully completed render template",
                extra={"operation": "render template", "config_path": config_path},
            )
            return rendered_template
        except Exception as e:
            ErrorHandler.handle_template_error(
                e,
                "render",
                config_path,
                context={"template_dir": template_dir, "output_path": output_path},
            )


class ConfigRenderingService:
    """Service for rendering and loading configuration data."""

    def __init__(
        self,
        template_renderer: TemplateRenderer | None = None,
    ):
        """
        Initialize the configuration rendering service.

        Args:
            template_renderer: Template renderer implementation.
        """
        self.template_renderer = template_renderer or JinjaTemplateRenderer()

    def _safe_load_yaml(self, raw: str, src: Path) -> ActionConfigMap:
        """Parse YAML and fail instantly on syntax OR empty content."""
        if not raw.strip():
            raise ConfigurationError(
                "Configuration file is empty",
                context={"file_path": str(src), "operation": "load_yaml"},
            )
        try:
            data = yaml.safe_load(raw)
        except YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            problem = getattr(exc, "problem", "syntax error")
            raise ConfigurationError(
                "YAML syntax error",
                context={
                    "file_path": str(src),
                    "line": mark.line + 1 if mark else None,
                    "column": mark.column + 1 if mark else None,
                    "problem": problem,
                    "operation": "parse_yaml",
                    "rendered_content": raw,
                },
                cause=exc,
            ) from exc
        if not data:
            raise ConfigurationError(
                "Configuration results in empty data",
                context={"file_path": str(src), "operation": "parse_yaml"},
            )
        return cast(ActionConfigMap, data)

    @staticmethod
    def _workflow_needs_schema(config: dict[str, Any]) -> bool:
        """Return True if any action in the workflow uses JSON mode (needs schemas)."""
        defaults: dict[str, Any] = config.get("defaults") or {}
        if defaults.get("json_mode") is not False:
            return True
        return any(a.get("json_mode") is True for a in (config.get("actions") or []))

    def _build_agent_entry_from_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Build agent entry dictionary from action configuration."""
        agent_entry = {
            "agent_type": action.get("name", "unknown"),
            "name": action.get("name"),
            "model_vendor": action.get("model_vendor", get_default("model_vendor")),
            "model_name": action.get("model_name", get_default("model_name")),
            "is_operational": get_default("is_operational"),
            "dependencies": [],
            "granularity": action.get("granularity", get_default("granularity")),
            "run_mode": get_default("run_mode"),
            "json_mode": action.get("json_mode", get_default("json_mode")),
        }

        kind = action.get("kind")
        if kind:
            agent_entry["kind"] = kind
            if kind == "tool":
                agent_entry["model_vendor"] = "tool"
                agent_entry["model_name"] = action.get("impl", action.get("name"))

        schema_value = action.get("schema")
        if schema_value:
            key = "schema_name" if isinstance(schema_value, str) else "schema"
            agent_entry[key] = schema_value

        if action.get("prompt"):
            agent_entry["prompt"] = action.get("prompt")

        return agent_entry

    def _validate_entry_with_pydantic(
        self, entry: dict[str, Any], agent_name: str, config_key: str
    ) -> ActionEntryDict:
        """Validate a single entry using Pydantic model."""
        try:
            entry_model = AgentConfig.model_validate(entry)
            return cast(ActionEntryDict, entry_model.model_dump(exclude_unset=True))
        except ValidationError as e:
            raise ConfigValidationError(
                config_key=config_key,
                reason=f"Invalid {config_key.replace('_', ' ')}",
                context={"action_name": entry.get("name", "unknown"), "agent_name": agent_name},
                cause=e,
            ) from e

    def _validate_new_format(
        self, config: ActionConfigMap, agent_name: str
    ) -> list[ActionEntryDict]:
        """Validate new format config with 'actions' key."""
        actions = config.get("actions", [])
        validated_entries = []
        for action in actions:
            agent_entry = self._build_agent_entry_from_action(cast(dict[str, Any], action))
            validated = self._validate_entry_with_pydantic(
                agent_entry, agent_name, "action_configuration"
            )
            validated_entries.append(validated)
        config["_validated_actions"] = validated_entries
        return validated_entries

    def _validate_legacy_format(
        self, config: ActionConfigMap, agent_name: str
    ) -> list[ActionEntryDict]:
        """Validate legacy format config with agent_name key."""
        agent_entries_list = cast(list[ActionEntryDict], config.get(agent_name))
        if agent_entries_list is None:
            raise ConfigValidationError(
                config_key="agent_configuration",
                reason="No agent configuration found",
                context={"agent_name": agent_name, "operation": "validate_config"},
            )

        validated_entries = []
        for entry in agent_entries_list:
            validated = self._validate_entry_with_pydantic(
                cast(dict[str, Any], entry), agent_name, "agent_configuration"
            )
            validated_entries.append(validated)
        config[agent_name] = validated_entries
        return validated_entries

    def _run_config_validator(
        self, validated_entries: list[ActionEntryDict], agent_name: str, project_root: Path
    ) -> None:
        """Run ConfigValidator on validated entries."""
        config_validator_instance = ConfigValidator()
        validation_payload = {
            "operation": "validate_agent_entries",
            "agent_config_data": validated_entries,
            "agent_name_context": agent_name,
            "project_dir": str(project_root),
        }
        if not config_validator_instance.validate(validation_payload):
            errors = config_validator_instance.get_errors()
            if errors:
                raise ConfigValidationError(
                    config_key="agent_configuration",
                    reason="Agent configuration validation failed",
                    context={
                        "agent_name": agent_name,
                        "errors": errors,
                        "operation": "validate_config",
                    },
                )

    def _validate_agent_config_block(
        self, config: ActionConfigMap, agent_name: str, project_root: Path | None = None
    ) -> None:
        """Validate the config - handle both old and new formats."""
        project_root_path = project_root or find_project_root()
        if project_root_path is None:
            project_root_path = Path.cwd()

        is_new_format = "actions" in config and "name" in config
        if is_new_format:
            validated_entries = self._validate_new_format(config, agent_name)
        else:
            validated_entries = self._validate_legacy_format(config, agent_name)

        self._run_config_validator(validated_entries, agent_name, project_root_path)

    @as_validation_error(ConfigurationError)
    def render_and_load_config(
        self,
        agent_name: str,
        config_path: str | Path,
        template_dir: str | Path,
        output_dir: str | Path | None = None,
        project_root: Path | None = None,
    ) -> ActionConfigMap:
        """
        Render templates and load configuration data.

        Args:
            agent_name: Name of the agent.
            config_path: Path to the agent configuration file.
            template_dir: Path to the template directory.
            output_dir: Path to the output directory.
            project_root: Optional project root for resolving relative paths.

        Returns:
            Parsed configuration data as a dictionary.

        Raises:
            FileNotFoundError: If required files are not found.
            TemplateRenderingError: If template rendering fails.
            ConfigurationError: If configuration parsing fails.
        """
        logger.debug(
            "Starting render and load config",
            extra={
                "operation": "render and load config",
                "agent_name": agent_name,
                "config_path": str(config_path),
                "template_dir": str(template_dir),
                "output_dir": str(output_dir),
            },
        )
        config_path_str = str(config_path)
        template_dir_str = str(template_dir)
        output_dir_str = str(output_dir) if output_dir is not None else None
        cfg_path = Path(config_path)
        if not cfg_path.exists():
            raise ConfigurationError(
                "Configuration file not found",
                context={"file_path": str(cfg_path), "operation": "render_and_load_config"},
            )
        if cfg_path.is_dir():
            raise ConfigurationError(
                "Expected a YAML/JSON file, got a directory",
                context={"file_path": str(cfg_path), "operation": "render_and_load_config"},
            )
        rendered_template = self.template_renderer.render(
            config_path_str, template_dir_str, output_dir_str, project_root=project_root
        )
        config = self._safe_load_yaml(rendered_template, cfg_path)
        if self._workflow_needs_schema(config):
            try:
                schema_validate_instance = SchemaValidator()
                schema_path = get_schema_path(
                    Path(project_root) if project_root else Path(template_dir).parent
                )
                schema_validate_instance.validate(
                    {
                        "agent_name": agent_name,
                        "schema_dir": resolve_relative_to(schema_path, Path(template_dir).parent),
                    }
                )
            except Exception as e:
                raise ConfigurationError(
                    "Schema validation failed",
                    context={
                        "agent_name": agent_name,
                        "template_dir": str(template_dir),
                        "operation": "validate_schema",
                    },
                    cause=e,
                ) from e
        self._validate_agent_config_block(config, agent_name, project_root=project_root)
        logger.debug(
            "Successfully completed render and load config",
            extra={"operation": "render and load config", "agent_name": agent_name},
        )
        return config
