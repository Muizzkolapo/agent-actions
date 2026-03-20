"""Project creation parameter validation."""

import logging
import os
import re
from pathlib import Path
from typing import Any

from agent_actions.validation.base_validator import BaseValidator

logger = logging.getLogger(__name__)


class ProjectValidator(BaseValidator):
    """Validates project name, directory, and template."""

    PROJECT_NAME_PATTERN = re.compile("^[a-zA-Z][a-zA-Z0-9_-]*$")
    RESERVED_NAMES: set[str] = {
        "agent",
        "actions",
        "cli",
        "core",
        "docs",
        "handlers",
        "schema",
        "templates",
        "test",
        "utils",
        "workflow",
    }

    def _validate_project_name_logic(self, project_name: str) -> None:
        """Validate the project name and add errors if invalid."""
        logger.debug("Validating project name: %s", project_name)
        if not project_name:
            self.add_error("Project name cannot be empty.")
            return
        if not self.PROJECT_NAME_PATTERN.match(project_name):
            self.add_error(
                f"Invalid project name: '{project_name}'. Project names must "
                f"start with a letter and contain only letters, numbers, "
                f"underscores, and hyphens."
            )
        if project_name.lower() in self.RESERVED_NAMES:
            self.add_error(f"Project name '{project_name}' is a reserved name and cannot be used.")

    def _validate_project_directory_logic(
        self, output_dir: Path, project_dir: Path, force: bool = False
    ) -> None:
        """Validate the project directory location and add errors if invalid."""
        logger.debug(
            "Validating project directory: %s within output directory: %s", project_dir, output_dir
        )
        if not self._ensure_path_exists(output_dir):
            self.add_error(f"Output directory does not exist: {output_dir}")
            return
        if not os.access(output_dir, os.W_OK):
            self.add_error(f"Output directory is not writable: {output_dir}")
        if self._ensure_path_exists(project_dir) and not force:
            self.add_error(
                f"Project directory already exists: {project_dir}. "
                f"Use --force to overwrite if intentional."
            )

    def _validate_project_template_logic(
        self, template: str, available_templates: list[str]
    ) -> None:
        """Validate the project template and add errors if not available."""
        logger.debug("Validating template: %s", template)
        if not template:
            self.add_error("Project template name cannot be empty.")
            return
        if template not in available_templates:
            templates_str = ", ".join(available_templates) if available_templates else "None"
            self.add_error(
                f"Template '{template}' not found. Available templates: {templates_str}."
            )

    def validate(self, data: Any, config: dict[str, Any] | None = None) -> bool:
        """Validate project creation parameters from the data dict."""
        if not self._prepare_validation(data):
            return self._complete_validation()
        project_name = data.get("project_name")
        output_dir = data.get("output_dir")
        project_dir = data.get("project_dir")
        template = data.get("template")
        available_templates = data.get("available_templates")
        force = data.get("force", False)
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
            return self._complete_validation()
        self._validate_project_name_logic(project_name)
        self._validate_project_directory_logic(output_dir, project_dir, force)
        self._validate_project_template_logic(template, available_templates)
        return self._complete_validation()
