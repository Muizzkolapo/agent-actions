"""
Configuration rendering service.

This module provides services for rendering configuration templates
and processing the resulting configuration data.
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Protocol, Union
from abc import ABC, abstractmethod

from agent_actions.workflow.render_workflow import render_pipeline_with_templates
from agent_actions.cli.exceptions import (
    TemplateRenderingError,
    ConfigurationError,
    FileNotFoundError
)

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
            logger.debug("Rendering pipeline with templates", extra={
                'config_path': config_path,
                'template_dir': template_dir,
                'output_path': output_path
            })
            
            # Validate inputs
            if not os.path.exists(config_path):
                raise FileNotFoundError(f"Configuration file not found: {config_path}")
                
            if not os.path.exists(template_dir):
                raise FileNotFoundError(f"Template directory not found: {template_dir}")
                
            if output_path and os.path.exists(output_path) and not os.access(output_path, os.W_OK):
                raise PermissionError(f"Output file is not writable: {output_path}")
            
            # Render the template
            rendered_template = render_pipeline_with_templates(
                config_path, 
                template_dir,
                output_path
            )
            
            logger.debug("Template rendering completed")
            return rendered_template
            
        except Exception as e:
            logger.error(f"Failed to render template: {str(e)}", exc_info=True)
            raise TemplateRenderingError(f"Failed to render template: {str(e)}") from e


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
            logger.debug("Parsing YAML configuration")
            
            if not config_data:
                raise ConfigurationError("Empty configuration data")
                
            config = yaml.safe_load(config_data)
            
            if not isinstance(config, dict):
                raise ConfigurationError(
                    f"Expected configuration to be a dictionary, got {type(config)}"
                )
                
            logger.debug("YAML parsing completed successfully")
            return config
            
        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error: {str(e)}", exc_info=True)
            raise ConfigurationError(f"Failed to parse YAML: {str(e)}") from e
        except Exception as e:
            logger.error(f"Configuration parsing error: {str(e)}", exc_info=True)
            raise ConfigurationError(f"Failed to parse configuration: {str(e)}") from e


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
            logger.debug(f"Writing output to file: {output_path}")
            
            # Create directory if it doesn't exist
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)
                
            # Write the content
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(content)
                
            logger.debug(f"Successfully wrote output to: {output_path}")
            
        except Exception as e:
            logger.error(f"Failed to write output: {str(e)}", exc_info=True)
            raise IOError(f"Failed to write output to {output_path}: {str(e)}") from e


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
        logger.info(f"Starting configuration rendering for agent: {agent_name}", extra={
            'agent_name': agent_name,
            'config_path': str(config_path),
            'template_dir': str(template_dir),
            'output_dir': str(output_dir)
        })
        
        try:
            # Convert paths to strings
            config_path_str = str(config_path)
            template_dir_str = str(template_dir)
            output_dir_str = str(output_dir)
            
            # Create output directory if it doesn't exist
            if not os.path.exists(output_dir_str):
                logger.debug(f"Creating output directory: {output_dir_str}")
                os.makedirs(output_dir_str, exist_ok=True)
                
            # Determine output path
            output_path = os.path.join(output_dir_str, f"{agent_name}.yml")
            logger.debug(f"Output path set to: {output_path}")
            
            # Render the template
            config_data_str = self.template_renderer.render(
                config_path_str,
                template_dir_str,
                output_path
            )
            
            # Parse the configuration
            config_data = self.config_parser.parse(config_data_str)
            
            logger.info(f"Successfully rendered and loaded configuration for agent: {agent_name}")
            return config_data
            
        except Exception as e:
            logger.error(f"Failed to render configuration for agent {agent_name}: {str(e)}", 
                         exc_info=True)
                         
            if isinstance(e, (FileNotFoundError, TemplateRenderingError, ConfigurationError)):
                raise
                
            raise ConfigurationError(f"Failed to render configuration: {str(e)}") from e


# Maintain backwards compatibility with the original API
class ConfigRenderer:
    """Static facade for backwards compatibility with old code."""
    
    @staticmethod
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