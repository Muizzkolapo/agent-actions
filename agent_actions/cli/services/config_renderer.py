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
from typing import Dict, Any, Optional, Protocol, Union
from abc import ABC, abstractmethod

from agent_actions.workflow.render_workflow import render_pipeline_with_templates
from agent_actions.cli.utils.path_validator import PathValidator
from agent_actions.cli.utils.service_logger import ServiceLogger
from agent_actions.cli.utils.error_handler import ErrorHandler
from agent_actions.cli.validators.config_validator import ConfigValidator
from agent_actions.cli.exceptions import ConfigurationError
from agent_actions.cli.exceptions import ConfigValidationError
from agent_actions.cli.validators.error_wrap import as_validation_error     # 🆕
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
            config_path: Path to the configuration file.
            template_dir: Path to the template directory.
            output_path: Optional path to save the rendered output.
            
        Returns:
            Rendered template as a string.
            
        Raises:
            TemplateRenderingError: If rendering fails.
        """
        try:
            ServiceLogger.log_operation_start(logger, "render template", 
                                           config_path=config_path,
                                           template_dir=template_dir,
                                           output_path=output_path)
            
            # Validate inputs
            PathValidator.validate_file(
                Path(config_path),
                "Configuration file",
                required=True,
                must_be_readable=True
            )
            
            PathValidator.validate_directory(
                Path(template_dir),
                "Template directory",
                required=True,
                must_be_readable=True
            )
            
            # Construct output file path if output directory is provided
            output_file_path = None
            if output_path:
                output_dir = Path(output_path)
                # Create output directory if it doesn't exist
                PathValidator.create_directory_if_needed(
                    output_dir,
                    "Output directory"
                )
                # Use the config file name for the output file
                config_name = Path(config_path).stem
                output_file_path = str(output_dir / f"{config_name}.yml")
            
            # Render the template
            rendered_template = render_pipeline_with_templates(
                config_path, 
                template_dir,
                output_file_path
            )
            
            ServiceLogger.log_operation_success(logger, "render template", 
                                             config_path=config_path)
            return rendered_template
            
        except Exception as e:
            ErrorHandler.handle_template_error(
                e,
                "render",
                config_path,
                context={'template_dir': template_dir, 'output_path': output_path}
            )


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
        
        # Validate output directory
        """PathValidator.validate_directory(
            Path(output_dir_str),
            "Output directory",
            required=True,
            must_be_writable=True
        )"""
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
        ConfigValidator.validate_list_config([config], "Agent configuration")
            
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