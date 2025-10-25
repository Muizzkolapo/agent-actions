"""
Project validation utilities.

This module provides utilities for validating project creation
parameters and ensuring they meet the required constraints.
"""
import os
import re
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from agent_actions.validation.base_validator import BaseValidator
logger = logging.getLogger(__name__)

class ProjectValidator(BaseValidator):
    """
    Handles project validation operations by inheriting from BaseValidator.
    Validates project name, directory, and template.
    """
    PROJECT_NAME_PATTERN = re.compile('^[a-zA-Z][a-zA-Z0-9_-]*$')
    RESERVED_NAMES: Set[str] = {'agent', 'actions', 'cli', 'core', 'docs', 'handlers', 'schema', 'templates', 'test', 'utils', 'workflow'}

    def _validate_project_name_logic(self, project_name: str) -> None:
        """
        Validates the project name and adds errors if any.
        """
        logger.debug(f'Validating project name: {project_name}')
        if not project_name:
            self.add_error('Project name cannot be empty.')
            return
        if not self.PROJECT_NAME_PATTERN.match(project_name):
            self.add_error(f"Invalid project name: '{project_name}'. Project names must start with a letter and contain only letters, numbers, underscores, and hyphens.")
        if project_name.lower() in self.RESERVED_NAMES:
            self.add_error(f"Project name '{project_name}' is a reserved name and cannot be used.")

    def _validate_project_directory_logic(self, output_dir: Path, project_dir: Path, force: bool=False) -> None:
        """
        Validates the project directory location and adds errors if any.
        """
        logger.debug(f'Validating project directory: {project_dir} within output directory: {output_dir}')
        if not self._ensure_path_exists(output_dir):
            self.add_error(f'Output directory does not exist: {output_dir}')
            return
        if not os.access(output_dir, os.W_OK):
            self.add_error(f'Output directory is not writable: {output_dir}')
        if self._ensure_path_exists(project_dir) and (not force):
            self.add_error(f'Project directory already exists: {project_dir}. Use --force to overwrite if intentional.')

    def _validate_project_template_logic(self, template: str, available_templates: List[str]) -> None:
        """
        Validates the project template and adds errors if any.
        """
        logger.debug(f'Validating template: {template}')
        if not template:
            self.add_error('Project template name cannot be empty.')
            return
        if template not in available_templates:
            self.add_error(f"Template '{template}' not found. Available templates: {(', '.join(available_templates) if available_templates else 'None')}.")

    def validate(self, data: Any, config: Optional[Dict[str, Any]]=None) -> bool:
        """
        Validates project creation parameters.

        Args:
            data: A dictionary containing the project parameters:
                - "project_name" (str): The name of the project.
                - "output_dir" (Path): The parent directory where the project will be created.
                - "project_dir" (Path): The full path to the project directory.
                - "template" (str): The name of the template to use.
                - "available_templates" (List[str]): A list of available template names.
                - "force" (bool, optional): Whether to allow overwriting an existing
                                            project directory. Defaults to False.
            config: Not used in this validator, but part of the interface.

        Returns:
            bool: True if all validations pass, False otherwise.
                  Errors are collected via self.add_error().
        """
        self.clear_errors()
        self.clear_warnings()
        if not isinstance(data, dict):
            self.add_error('Validation data must be a dictionary.')
            return False
        project_name = data.get('project_name')
        output_dir = data.get('output_dir')
        project_dir = data.get('project_dir')
        template = data.get('template')
        available_templates = data.get('available_templates')
        force = data.get('force', False)
        if not isinstance(project_name, str):
            self.add_error("Data field 'project_name' must be a string.")
        if not isinstance(output_dir, Path):
            self.add_error("Data field 'output_dir' must be a Path object.")
        if not isinstance(project_dir, Path):
            self.add_error("Data field 'project_dir' must be a Path object.")
        if not isinstance(template, str):
            self.add_error("Data field 'template' must be a string.")
        if not isinstance(available_templates, list):
            self.add_error("Data field 'available_templates' must be a list.")
        if not isinstance(force, bool):
            self.add_error("Data field 'force' must be a boolean.")
        if self.has_errors():
            return False
        self._validate_project_name_logic(project_name)
        self._validate_project_directory_logic(output_dir, project_dir, force)
        self._validate_project_template_logic(template, available_templates)
        return not self.has_errors()