"""
Render validation utilities.

This module provides utilities for validating template rendering
parameters and ensuring they meet the required constraints.
"""

import os
import logging
from pathlib import Path
from typing import Tuple

from agent_actions.handlers.file_handler import FileHandler
from agent_actions.cli.exceptions import ValidationError, FileNotFoundError

logger = logging.getLogger(__name__)


class RenderValidator:
    """Handles render validation operations."""

    @classmethod
    def validate_agent_paths(cls, agent_name: str) -> Tuple[Path, Path]:
        """
        Validate and get the agent configuration paths.
        
        Args:
            agent_name: Name of the agent template to validate.
            
        Returns:
            Tuple of (agent_config_dir, agent_config_file)
            
        Raises:
            FileNotFoundError: If the agent configuration file or directory is not found.
        """
        try:
            # Get agent directories
            agent_config_dir_str, _, _ = FileHandler.get_agent_paths(agent_name)
            agent_config_dir = Path(agent_config_dir_str)
            
            if not agent_config_dir.exists():
                raise FileNotFoundError(
                    f"Agent configuration directory not found: {agent_config_dir}"
                )
            
            # Find the configuration file
            agent_config_file_str = FileHandler.find_config_file(
                str(agent_config_dir), 
                f"{agent_name}.yml"
            )
            
            if not agent_config_file_str:
                raise FileNotFoundError(
                    f"Missing configuration file: {agent_name}.yml"
                )
            
            agent_config_file = Path(agent_config_file_str)
            return agent_config_dir, agent_config_file
            
        except Exception as e:
            if isinstance(e, FileNotFoundError):
                raise
            raise FileNotFoundError(
                f"Failed to locate agent configuration: {str(e)}"
            ) from e

    @classmethod
    def validate_template_directory(cls, template_dir: Path) -> None:
        """
        Validate that the template directory exists and is readable.
        
        Args:
            template_dir: Path to template directory.
            
        Raises:
            ValidationError: If the template directory is invalid.
        """
        if not template_dir.exists():
            raise ValidationError(
                f"Template directory does not exist: {template_dir}"
            )
        
        if not template_dir.is_dir():
            raise ValidationError(
                f"Template path is not a directory: {template_dir}"
            )
        
        if not os.access(template_dir, os.R_OK):
            raise ValidationError(
                f"Template directory is not readable: {template_dir}"
            )

    @classmethod
    def validate_output_file(cls, output_file: str) -> None:
        """
        Validate that the output file can be written.
        
        Args:
            output_file: Path to output file.
            
        Raises:
            ValidationError: If the output file path is invalid.
        """
        if not output_file:
            return
            
        output_path = Path(output_file)
        output_dir = output_path.parent
        
        if not output_dir.exists():
            raise ValidationError(
                f"Output directory does not exist: {output_dir}"
            )
        
        if not os.access(output_dir, os.W_OK):
            raise ValidationError(
                f"Output directory is not writable: {output_dir}"
            )
        
        if output_path.exists() and not os.access(output_path, os.W_OK):
            raise ValidationError(
                f"Output file is not writable: {output_path}"
            )