"""
Configuration rendering service.

This module provides services for rendering configuration templates
and processing the resulting configuration data.
"""

import os
import yaml
from ruamel.yaml import YAML, YAMLError 
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union
from abc import ABC, abstractmethod

from agent_actions.workflow.render_workflow import render_pipeline_with_templates
from agent_actions.cli.validators.path_validator import PathValidator
from agent_actions.cli.utils.service_logger import ServiceLogger
from agent_actions.cli.utils.error_handler import ErrorHandler
from agent_actions.cli.exceptions import ConfigurationError
from agent_actions.cli.exceptions import ConfigValidationError
from agent_actions.cli.validators.error_wrap import as_validation_error     # 🆕
from agent_actions.cli.validators.schema_validator import SchemaValidator
from agent_actions.cli.validators.config_validator import ConfigValidator
from pydantic import ValidationError
from agent_actions.models.config_schema import AgentConfig
from agent_actions.handlers.agent_handlers import AgentManager

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
        pass


class ConfigParser(ABC):
    """Abstract interface for configuration parsing."""
    
    @abstractmethod
    def parse(self, config_data: str) -> Dict[str, Any]:
        """
        Parse configuration data from a string.
        
        Args:
            config_data: Configuration data as a string.
            
        Returns:
            Parsed configuration as a dictionary.
            
        Raises:
            ConfigurationError: If parsing fails.
        """
        pass


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
        pass


class JinjaTemplateRenderer(TemplateRenderer):
    """Template renderer implementation using Jinja."""

    def render(self, config_path: str, template_dir: str, output_path: Optional[str] = None) -> str:
        """
        Render a template with the given configuration using Jinja.

        Args:
            config_path: Path to the configuration file (as string).
            template_dir: Path to the template directory (as string).
            output_path: Optional path to save the rendered output (as string, can be a directory path).

        Returns:
            Rendered template as a string.

        Raises:
            ValueError: If input validation fails (caught by the generic handler).
            Any exception from render_pipeline_with_templates or ErrorHandler.
        """
        # Argument names from the original user-provided function are config_path, template_dir, output_path
        # These are used directly as strings. Path conversion happens when creating the 'data' dicts.
        try:
            ServiceLogger.log_operation_start(logger, "render template",
                                           config_path=config_path,
                                           template_dir=template_dir,
                                           output_path=output_path)

            path_validator = PathValidator() # Instantiate the validator
            all_validations_passed = True
            error_messages: list[str] = []

            # 1. Validate Configuration File
            data_config_file = {
                "operation": "validate_file",
                "path": Path(config_path), # Convert string path to Path object
                "path_name": "Configuration file",
                "required": True,
                "must_be_readable": True
            }
            if not path_validator.validate(data_config_file):
                all_validations_passed = False
                error_messages.extend(path_validator.get_errors())

            # 2. Validate Template Directory
            #    Proceed even if config file validation failed, to collect all path errors,
            #    or use 'if all_validations_passed:' to fail fast.
            #    For this example, we'll collect all path errors.
            data_template_dir = {
                "operation": "validate_directory",
                "path": Path(template_dir), # Convert string path to Path object
                "path_name": "Template directory",
                "required": True,
                "must_be_readable": True
            }
            if not path_validator.validate(data_template_dir):
                all_validations_passed = False
                error_messages.extend(path_validator.get_errors())

            # 3. Validate and potentially create Output Directory
            output_file_to_write: Optional[str] = None # Full path to the output file
            if output_path: # output_path is the directory where the file will be saved
                output_dir_as_path = Path(output_path)
                data_output_dir = {
                    "operation": "ensure_directory_exists",
                    "path": output_dir_as_path,
                    "path_name": "Output directory",
                    "create_if_missing": True,
                    "must_be_writable_after_creation": True
                }
                if not path_validator.validate(data_output_dir):
                    all_validations_passed = False
                    error_messages.extend(path_validator.get_errors())
                else:
                    # If output directory is valid/created, construct the output file path
                    config_name_stem = Path(config_path).stem
                    output_file_to_write = str(output_dir_as_path / f"{config_name_stem}.yml")
            else:
                logger.info("No output path provided; template will be rendered to memory/stdout.")


            # 4. If any validation failed, raise an error
            if not all_validations_passed:
                final_error_message = "Input validation failed for template rendering: \n" + "\n".join(f"- {msg}" for msg in error_messages)
                raise ValueError(final_error_message) # This will be caught by the except block

            # If all validations passed, proceed to render the template
            logger.info("All path validations passed. Proceeding to render template.")
            rendered_template = render_pipeline_with_templates(
                config_path,    # Pass original string path
                template_dir,   # Pass original string path
                output_file_to_write # This is the full file path string, or None
            )

            ServiceLogger.log_operation_success(logger, "render template",
                                             config_path=config_path)
            return rendered_template
        except Exception as e: # This will catch the ValueError from validation, or any other exception
            ErrorHandler.handle_template_error(
                e,
                "render",
                config_path, # Original string path
                context={'template_dir': template_dir, 'output_path': output_path}
            )
            # The original ErrorHandler.handle_template_error in the placeholder re-raises 'e'.
            # If your actual ErrorHandler does not re-raise, and this render method
            # must always return a string or raise a specific TemplateRenderingError,
            # you might need to add 'raise TemplateRenderingError(str(e)) from e' here,
            # or ensure the return "" is appropriate for your contract on failure.
            # Given the placeholder re-raises, this is fine.
            # If ErrorHandler consumes the exception and doesn't re-raise,
            # and the function must return a string, returning an empty string
            # or a specific error string might be necessary.
            # The original code implicitly returned None if ErrorHandler didn't re-raise.
            # Let's match that by allowing the re-raise from ErrorHandler.
            # If ErrorHandler *doesn't* re-raise, then an empty string or specific error return is needed.
            # For now, assuming ErrorHandler re-raises as per the placeholder.
            # If it doesn't, the 'return ""' from the previous version might be what was intended
            # if the original function signature implies a string is always returned.
            # Let's assume the original intent was for ErrorHandler to manage the exception flow (e.g. re-raise or exit)
            # If not, and a string must be returned:
            # return f"Error during rendering: {type(e).__name__}" # Or simply ""
            raise # Re-raise the exception if ErrorHandler didn't (our placeholder does)


class YAMLConfigParser(ConfigParser):
    """Configuration parser implementation for YAML."""
    
    def parse(self, config_data: str) -> Dict[str, Any]:
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
                raise ConfigurationError("Empty configuration data")
                
            config = yaml.safe_load(config_data)
            
            if not isinstance(config, dict):
                raise ConfigurationError(
                    f"Expected configuration to be a dictionary, got {type(config)}"
                )
                
            ServiceLogger.log_operation_success(logger, "parse YAML configuration")
            return config
            
        except YAMLError as e:
            ErrorHandler.handle_config_error(
                e,
                "parse",
                "YAML configuration",
                context={'config_data': config_data}
            )
        except Exception as e:
            ErrorHandler.handle_config_error(
                e,
                "parse",
                "configuration",
                context={'config_data': config_data}
            )


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
            ServiceLogger.log_operation_start(logger, "write output", 
                                           output_path=output_path)
            
            # Create directory if it doesn't exist
            output_dir = os.path.dirname(output_path)
            if output_dir:
                PathValidator.create_directory_if_needed(
                    Path(output_dir),
                    "Output directory"
                )
                
            # Write the content
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(content)
                
            ServiceLogger.log_operation_success(logger, "write output", 
                                             output_path=output_path)
            
        except Exception as e:
            ErrorHandler.handle_file_error(
                e,
                "write",
                output_path,
                context={'content_length': len(content)}
            )


class ConfigRenderingService:
    """Service for rendering and loading configuration data."""
    
    def __init__(
        self,
        template_renderer: TemplateRenderer = None,
        config_parser: ConfigParser = None,
        output_writer: OutputWriter = None
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


    def _safe_load_yaml(self, raw: str, src: Path) -> Dict[str, Any]:
        """Parse YAML and fail instantly on syntax OR empty content."""
        if not raw.strip():
            raise ConfigurationError(f"Configuration file is empty: {src}")
        try:
            data = YAML(typ="safe").load(raw)
        except YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            where = f"(line {mark.line+1}, col {mark.column+1})" if mark else ""
            problem = getattr(exc, "problem", "syntax error")
            raise ConfigurationError(
                f"YAML syntax error in {src} {where}: {problem}"
            )
        if not data:
            raise ConfigurationError(f"Configuration results in empty data: {src}")
        return data
    
    def _validate_agent_config_block(self, config: Dict[str, Any], agent_name: str) -> None:
        """
        Validate the full agent config using ConfigValidator.
        """
        current_directory = Path.cwd() 
        project_root_path = AgentManager.find_project_root(start_path=current_directory)
        agent_entries_list = config.get(agent_name)
        validated_entries = []
        for entry in agent_entries_list:
            try:
                entry_model = AgentConfig.model_validate(entry)
                validated_entries.append(entry_model.model_dump(exclude_unset=True))
            except ValidationError as e:
                raise ConfigValidationError(f"Invalid agent configuration: {e}") from e

        config[agent_name] = validated_entries

        config_validator_instance = ConfigValidator()
        validation_payload = {
            "operation": "validate_agent_entries",
            "agent_config_data": validated_entries,
            "agent_name_context": agent_name,
            "project_dir": str(project_root_path)
        }

        if not config_validator_instance.validate(validation_payload):
            errors = config_validator_instance.get_errors()
            if errors:
                raise ConfigValidationError(
                    f"Agent configuration validation failed for '{agent_name}': {errors}"
                )

    @as_validation_error(ConfigurationError)
    def render_and_load_config(
        self,
        agent_name: str,
        config_path: Union[str, Path],
        template_dir: Union[str, Path],
        output_dir: Union[str, Path]
    ) -> Dict[str, Any]:
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
        ServiceLogger.log_operation_start(logger, "render and load config",
                                        agent_name=agent_name,
                                        config_path=str(config_path),
                                        template_dir=str(template_dir),
                                        output_dir=str(output_dir))
        
        # Convert paths to strings
        config_path_str = str(config_path)
        template_dir_str = str(template_dir)
        output_dir_str = str(output_dir)
        
        cfg_path = Path(config_path)
        if not cfg_path.exists():
           raise ConfigurationError(f"Configuration file not found: {cfg_path}")
        if cfg_path.is_dir():
            raise ConfigurationError(f"Expected a YAML/JSON file, got a directory: {cfg_path}")       
        # Render the template
        rendered_template = self.template_renderer.render(
            config_path_str,
            template_dir_str,
            output_dir_str
        )
        config = self._safe_load_yaml(rendered_template, cfg_path)
        try:
            schema_validate_instance = SchemaValidator()
            schema_validate_instance.validate(agent_name, Path(template_dir))
        except Exception as e:
            raise ConfigurationError(f"Schema validation failed: {e}") from None
        self._validate_agent_config_block(config, agent_name)
            
        ServiceLogger.log_operation_success(logger, "render and load config",
                                           agent_name=agent_name)
    
        return config


# Maintain backwards compatibility with the original API
class ConfigRenderer:
    """Static facade for backwards compatibility with old code."""
    @as_validation_error(ConfigValidationError)
    def _safe_load_yaml(self, raw: str, src: Path):
        """Parse YAML, turning low-level YAMLError into our own exception."""
        try:
            return yaml.safe_load(raw) or {}
        except yaml.MarkedYAMLError as exc:
            # Build a human sentence: file, 1-based line/col, parser complaint
            mark = exc.problem_mark            # has .line & .column (0-based)
            msg  = exc.problem or "syntax error"
            raise ConfigValidationError(
                f"YAML syntax error in {src.name} "
                f"(line {mark.line+1}, col {mark.column+1}): {msg}"
            ) from None    
    @as_validation_error(ConfigValidationError)
    def render_and_load_config(
        agent_name: str,
        config_path: Path,
        template_dir: Path,
        output_dir: Path
    ) -> Dict[str, Any]:
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