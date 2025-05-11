"""
Project validation utilities.

This module provides utilities for validating project creation
parameters and ensuring they meet the required constraints.
"""

import os
import re
import logging
from pathlib import Path
from typing import List, Set

from agent_actions.cli.exceptions import ValidationError, PermissionError

logger = logging.getLogger(__name__)


class ProjectValidator:
    """Handles project validation operations."""
    
    # Project name validation pattern
    PROJECT_NAME_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]*$')
    
    # Reserved names that cannot be used for projects
    RESERVED_NAMES = {
        'agent', 'actions', 'cli', 'core', 'docs', 'handlers', 
        'schema', 'templates', 'test', 'utils', 'workflow'
    }

    @classmethod
    def validate_project_name(cls, project_name: str) -> None:
        """
        Validate the project name.
        
        Args:
            project_name: Name of the project to validate.
            
        Raises:
            ValidationError: If the project name is invalid.
        """
        logger.debug(f"Validating project name: {project_name}")
        
        if not project_name:
            raise ValidationError("Project name cannot be empty")
        
        if not cls.PROJECT_NAME_PATTERN.match(project_name):
            raise ValidationError(
                f"Invalid project name: {project_name}. "
                "Project names must start with a letter and contain only "
                "letters, numbers, underscores, and hyphens."
            )
        
        if project_name.lower() in cls.RESERVED_NAMES:
            raise ValidationError(
                f"'{project_name}' is a reserved name and cannot be used as a project name"
            )

    @classmethod
    def validate_project_directory(cls, output_dir: Path, project_dir: Path, force: bool = False) -> None:
        """
        Validate the project directory location.
        
        Args:
            output_dir: Parent directory where project will be created.
            project_dir: Full path to the project directory.
            force: Whether to allow overwriting existing directory.
            
        Raises:
            ValidationError: If the directory validation fails.
            PermissionError: If there's a permission issue.
        """
        logger.debug(f"Validating output directory: {output_dir}")
        
        if not output_dir.exists():
            raise ValidationError(f"Output directory does not exist: {output_dir}")
        
        if not os.access(output_dir, os.W_OK):
            raise PermissionError(f"Output directory is not writable: {output_dir}")
        
        if project_dir.exists() and not force:
            raise ValidationError(
                f"Project directory already exists: {project_dir}. "
                "Use --force to overwrite."
            )

    @classmethod
    def validate_template(cls, template: str, available_templates: List[str]) -> None:
        """
        Validate the project template.
        
        Args:
            template: Name of the template to validate.
            available_templates: List of available template names.
            
        Raises:
            ValidationError: If the template is invalid.
        """
        logger.debug(f"Validating template: {template}")
        
        if template not in available_templates:
            raise ValidationError(
                f"Template '{template}' not found. "
                f"Available templates: {', '.join(available_templates)}"
            )