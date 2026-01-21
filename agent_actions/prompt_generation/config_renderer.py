"""
Configuration rendering service.

This module provides services for rendering configuration templates
and processing the resulting configuration data.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional, Union, List, cast

import yaml
from yaml import YAMLError
from pydantic import ValidationError

from agent_actions.cli.utils.error_handler import ErrorHandler
from agent_actions.cli.utils.error_wrap import as_validation_error
from agent_actions.cli.utils.service_logger import ServiceLogger
from agent_actions.errors import ConfigurationError, ConfigValidationError
from agent_actions.llm_invocation.realtime.agent_handlers import AgentManager
from agent_actions.prompt_generation.render_workflow import render_pipeline_with_templates
from agent_actions.response_processing.config_schema import AgentConfig
from agent_actions.response_processing.config_types import AgentEntryDict, AgentConfigMap
from agent_actions.validation.config_validator import ConfigValidator
from agent_actions.validation.path_validator import PathValidator
from agent_actions.validation.schema_validator import SchemaValidator

logger = logging.getLogger(__name__)


class TemplateRenderer(ABC):
    """Abstract interface for template rendering."""

    @abstractmethod
    def render(self, config_path: str, template_dir: str, output_path: Optional[str] = None) -> str:
        """
        Render a template with the given configuration.

        Args:
            config_path: Path to the configuration file.
            template_dir: Path to the template directory.
            output_path: Optional path to save the rendered output.

        Returns:
            Rendered template as a string.

        Raises:
            TemplateRenderingError: If rendering fails.
        """


class ConfigParser(ABC):
    """Abstract interface for configuration parsing."""

    @abstractmethod
    def parse(self, config_data: str) -> AgentConfigMap:
        """
        Parse configuration data from a string.

        Args:
            config_data: Configuration data as a string.

        Returns:
            Parsed configuration as a dictionary.

        Raises:
            ConfigurationError: If parsing fails.
        """


class OutputWriter(ABC):
    """Abstract interface for writing output to a file."""

    @abstractmethod
    def write(self, output_path: str, content: str) -> None:
        """
        Write content to the specified path.

        Args:
            output_path: Path to write the content to.
            content: Content to write.

        Raises:
            IOError: If writing fails.
        """


class JinjaTemplateRenderer(TemplateRenderer):
    """Template renderer implementation using Jinja."""

    def render(
        self,
        config_path: str,
        template_dir: str,
        output_path: Optional[str] = None,
    ) -> str:
        """
        Render a template with the given configuration using Jinja.

        Args:
            config_path: Path to the configuration file (as string).
            template_dir: Path to the template directory (as string).
            output_path: Optional path to save the rendered output
                (as string, can be a directory path).

        Returns:
            Rendered template as a string.

        Raises:
            ValueError: If input validation fails
                (caught by the generic handler).
            Any exception from render_pipeline_with_templates or
                ErrorHandler.
        """
        try:
            ServiceLogger.log_operation_start(
                logger,
                "render template",
                user_facing=True,
                config_path=config_path,
                template_dir=template_dir,
                output_path=output_path,
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
            output_file_to_write: Optional[str] = None
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
            rendered_template = render_pipeline_with_templates(config_path, template_dir)
            if output_file_to_write:
                with open(output_file_to_write, "w", encoding="utf-8") as f:
                    f.write(rendered_template)
                logger.info("Rendered template saved to: %s", output_file_to_write)
            ServiceLogger.log_operation_success(
                logger, "render template", user_facing=True, config_path=config_path
            )
            return rendered_template
        except Exception as e:
            ErrorHandler.handle_template_error(
                e,
                "render",
                config_path,
                context={"template_dir": template_dir, "output_path": output_path},
            )
            raise


class YAMLConfigParser(ConfigParser):
    """Configuration parser implementation for YAML."""

    def parse(self, config_data: str) -> AgentConfigMap:
        """
        Parse YAML configuration data from a string.

        Args:
            config_data: YAML configuration data as a string.

        Returns:
            Parsed configuration as a dictionary.

        Raises:
            ConfigurationError: If parsing fails.
        """
        try:
            ServiceLogger.log_operation_start(logger, "parse YAML configuration")
            if not config_data:
                raise ConfigurationError(
                    "Empty configuration data", context={"operation": "parse_yaml"}
                )
            config = yaml.safe_load(config_data)
            if not isinstance(config, dict):
                raise ConfigurationError(
                    "Expected configuration to be a dictionary",
                    context={"operation": "parse_yaml", "actual_type": type(config).__name__},
                )
            ServiceLogger.log_operation_success(logger, "parse YAML configuration")
            return cast(AgentConfigMap, config)
        except YAMLError as e:
            ErrorHandler.handle_config_error(
                e, "parse", "YAML configuration", context={"config_data": config_data}
            )
            raise
        except Exception as e:
            ErrorHandler.handle_config_error(
                e, "parse", "configuration", context={"config_data": config_data}
            )
            raise


class FileOutputWriter(OutputWriter):
    """Output writer implementation for files."""

    def write(self, output_path: str, content: str) -> None:
        """
        Write content to a file.

        Args:
            output_path: Path to the output file.
            content: Content to write.

        Raises:
            IOError: If writing fails.
        """
        try:
            ServiceLogger.log_operation_start(logger, "write output", output_path=output_path)
            output_dir = Path(output_path).parent
            if output_dir and not output_dir.exists():
                output_dir.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)
            ServiceLogger.log_operation_success(logger, "write output", output_path=output_path)
        except Exception as e:
            ErrorHandler.handle_file_error(
                e, "write", output_path, context={"content_length": len(content)}
            )


class ConfigRenderingService:
    """Service for rendering and loading configuration data."""

    def __init__(
        self,
        template_renderer: TemplateRenderer = None,
        config_parser: ConfigParser = None,
        output_writer: OutputWriter = None,
    ):
        """
        Initialize the configuration rendering service.

        Args:
            template_renderer: Template renderer implementation.
            config_parser: Configuration parser implementation.
            output_writer: Output writer implementation.
        """
        self.template_renderer = template_renderer or JinjaTemplateRenderer()
        self.config_parser = config_parser or YAMLConfigParser()
        self.output_writer = output_writer or FileOutputWriter()

    def _safe_load_yaml(self, raw: str, src: Path) -> AgentConfigMap:
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
            ) from exc
        if not data:
            raise ConfigurationError(
                "Configuration results in empty data",
                context={"file_path": str(src), "operation": "parse_yaml"},
            )
        return cast(AgentConfigMap, data)

    def _build_agent_entry_from_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Build agent entry dictionary from action configuration."""
        agent_entry = {
            "agent_type": action.get("name", "unknown"),
            "name": action.get("name"),
            "model_vendor": action.get("vendor", "openai"),
            "model_name": action.get("model", "gpt-4"),
            "is_operational": True,
            "dependencies": [],
            "granularity": action.get("granularity", "record"),
            "run_mode": "online",
            "few_shot": action.get("few_shot", 0),
            "json_mode": action.get("json_mode", True),
        }

        if action.get("kind") == "tool":
            agent_entry["model_vendor"] = "tool"
            agent_entry["model_name"] = action.get("impl", action.get("name"))

        schema_value = action.get("schema") or action.get("output_schema")
        if schema_value:
            key = "schema_name" if isinstance(schema_value, str) else "schema"
            agent_entry[key] = schema_value

        if action.get("prompt"):
            agent_entry["prompt"] = action.get("prompt")

        return agent_entry

    def _validate_entry_with_pydantic(
        self, entry: Dict[str, Any], agent_name: str, config_key: str
    ) -> AgentEntryDict:
        """Validate a single entry using Pydantic model."""
        try:
            entry_model = AgentConfig.model_validate(entry)
            return entry_model.model_dump(exclude_unset=True)
        except ValidationError as e:
            raise ConfigValidationError(
                config_key=config_key,
                reason=f"Invalid {config_key.replace('_', ' ')}",
                context={"action_name": entry.get("name", "unknown"), "agent_name": agent_name},
                cause=e,
            ) from e

    def _validate_new_format(self, config: AgentConfigMap, agent_name: str) -> List[AgentEntryDict]:
        """Validate new format config with 'actions' key."""
        actions = config.get("actions", [])
        validated_entries = []
        for action in actions:
            agent_entry = self._build_agent_entry_from_action(action)
            validated = self._validate_entry_with_pydantic(
                agent_entry, agent_name, "action_configuration"
            )
            validated_entries.append(validated)
        config["_validated_actions"] = validated_entries
        return validated_entries

    def _validate_legacy_format(
        self, config: AgentConfigMap, agent_name: str
    ) -> List[AgentEntryDict]:
        """Validate legacy format config with agent_name key."""
        agent_entries_list = cast(List[AgentEntryDict], config.get(agent_name))
        if agent_entries_list is None:
            raise ConfigValidationError(
                config_key="agent_configuration",
                reason="No agent configuration found",
                context={"agent_name": agent_name, "operation": "validate_config"},
            )

        validated_entries = []
        for entry in agent_entries_list:
            validated = self._validate_entry_with_pydantic(entry, agent_name, "agent_configuration")
            validated_entries.append(validated)
        config[agent_name] = validated_entries
        return validated_entries

    def _run_config_validator(
        self, validated_entries: List[AgentEntryDict], agent_name: str, project_root: Path
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

    def _validate_agent_config_block(self, config: AgentConfigMap, agent_name: str) -> None:
        """Validate the config - handle both old and new formats."""
        project_root_path = AgentManager.find_project_root(start_path=Path.cwd())

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
        config_path: Union[str, Path],
        template_dir: Union[str, Path],
        output_dir: Union[str, Path],
    ) -> AgentConfigMap:
        """
        Render templates and load configuration data.

        Args:
            agent_name: Name of the agent.
            config_path: Path to the agent configuration file.
            template_dir: Path to the template directory.
            output_dir: Path to the output directory.

        Returns:
            Parsed configuration data as a dictionary.

        Raises:
            FileNotFoundError: If required files are not found.
            TemplateRenderingError: If template rendering fails.
            ConfigurationError: If configuration parsing fails.
        """
        ServiceLogger.log_operation_start(
            logger,
            "render and load config",
            agent_name=agent_name,
            config_path=str(config_path),
            template_dir=str(template_dir),
            output_dir=str(output_dir),
        )
        config_path_str = str(config_path)
        template_dir_str = str(template_dir)
        output_dir_str = str(output_dir)
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
            config_path_str, template_dir_str, output_dir_str
        )
        config = self._safe_load_yaml(rendered_template, cfg_path)
        try:
            schema_validate_instance = SchemaValidator()
            schema_validate_instance.validate(agent_name, Path(template_dir))
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
        self._validate_agent_config_block(config, agent_name)
        ServiceLogger.log_operation_success(logger, "render and load config", agent_name=agent_name)
        return config


class ConfigRenderer:
    """Static facade for backwards compatibility with old code."""

    @as_validation_error(ConfigValidationError)
    def _safe_load_yaml(self, raw: str, src: Path) -> AgentConfigMap:
        """Parse YAML, turning low-level YAMLError into our own
        exception."""
        try:
            loaded_config = yaml.safe_load(raw) or {}
            return cast(AgentConfigMap, loaded_config)
        except yaml.MarkedYAMLError as exc:
            mark = exc.problem_mark
            msg = exc.problem or "syntax error"
            raise ConfigValidationError(
                config_key="yaml_syntax",
                reason="YAML syntax error",
                context={
                    "file_name": src.name,
                    "line": mark.line + 1,
                    "column": mark.column + 1,
                    "problem": msg,
                    "operation": "parse_yaml",
                },
            ) from exc
        except Exception as exc:
            raise ConfigValidationError(
                config_key="configuration_format",
                reason="Configuration format error",
                context={"file_name": src.name, "operation": "parse_yaml"},
                cause=exc,
            ) from exc

    @staticmethod
    @as_validation_error(ConfigValidationError)
    def render_and_load_config(
        agent_name: str, config_path: Path, template_dir: Path, output_dir: Path
    ) -> AgentConfigMap:
        """
        Static method for backwards compatibility.

        Args:
            agent_name: Name of the agent.
            config_path: Path to the agent configuration file.
            template_dir: Path to the template directory.
            output_dir: Path to the output directory.

        Returns:
            Parsed configuration data as a dictionary.
        """
        service = ConfigRenderingService()
        return service.render_and_load_config(agent_name, config_path, template_dir, output_dir)
