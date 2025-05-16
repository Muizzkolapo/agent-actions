"""
Render validation utilities.

This module provides utilities for validating template rendering
parameters and ensuring they meet the required constraints.
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Assuming your BaseValidator is now in validators.base_validator
from .base_validator import BaseValidator
# Assuming FileHandler and custom exceptions exist.
# Exceptions like ValidationError, FileNotFoundError will no longer be directly raised
# by the validation logic but will be reported via self.add_error().
from agent_actions.handlers.file_handler import FileHandler
# from agent_actions.cli.exceptions import ValidationError, FileNotFoundError

logger = logging.getLogger(__name__)


class RenderValidator(BaseValidator):
    """
    Handles render validation operations by inheriting from BaseValidator.
    """

    def _validate_agent_paths_logic(self, agent_name: str) -> Optional[Tuple[Path, Path]]:
        """
        Validates and gets agent configuration paths. Adds errors if validation fails.
        Returns a tuple of (agent_config_dir, agent_config_file) if successful, else None.
        """
        logger.debug(f"Validating agent paths for agent: {agent_name}")
        try:
            # Get agent directories using FileHandler
            # These FileHandler methods might raise exceptions or return None/empty strings
            agent_config_dir_str, _, _ = FileHandler.get_agent_paths(agent_name)
            if not agent_config_dir_str:
                self.add_error(f"Could not retrieve agent configuration directory path for agent: {agent_name}.")
                return None
            
            agent_config_dir = Path(agent_config_dir_str)

            if not self._ensure_path_exists(agent_config_dir):
                self.add_error(f"Agent configuration directory not found: {agent_config_dir} for agent: {agent_name}.")
                return None
            if not self._is_directory(agent_config_dir):
                self.add_error(f"Agent configuration path is not a directory: {agent_config_dir} for agent: {agent_name}.")
                return None

            # Find the configuration file using FileHandler
            # Ensure expected_config_filename reflects actual naming convention (e.g. .yml, .yaml)
            expected_config_filename = f"{agent_name}.yml" # or make this more flexible
            agent_config_file_str = FileHandler.find_config_file(
                str(agent_config_dir),
                expected_config_filename # Original code used agent_name.yml
            )

            if not agent_config_file_str:
                self.add_error(f"Missing configuration file '{expected_config_filename}' in {agent_config_dir} for agent: {agent_name}.")
                # Attempt to find .yaml as a fallback or based on other conventions if necessary
                expected_config_filename_yaml = f"{agent_name}.yaml"
                agent_config_file_str_yaml = FileHandler.find_config_file(str(agent_config_dir), expected_config_filename_yaml)
                if not agent_config_file_str_yaml:
                    self.add_error(f"Also tried missing configuration file '{expected_config_filename_yaml}' in {agent_config_dir} for agent: {agent_name}.")
                    return None
                agent_config_file_str = agent_config_file_str_yaml


            agent_config_file = Path(agent_config_file_str)
            if not self._is_file(agent_config_file): # find_config_file should return a file, but double check
                self.add_error(f"Agent configuration path found but is not a file: {agent_config_file} for agent: {agent_name}.")
                return None

            logger.info(f"Agent paths validated successfully for {agent_name}: {agent_config_dir}, {agent_config_file}")
            return agent_config_dir, agent_config_file

        except Exception as e:
            logger.error(f"Failed to locate or validate agent configuration for '{agent_name}': {e}", exc_info=True)
            self.add_error(f"Error during agent path validation for '{agent_name}': {e}.")
            return None

    def _validate_template_directory_logic(self, template_dir: Path) -> None:
        """
        Validates that the template directory exists and is readable. Adds errors if not.
        """
        logger.debug(f"Validating template directory: {template_dir}")
        if not self._ensure_path_exists(template_dir):
            self.add_error(f"Template directory does not exist: {template_dir}.")
            return
        if not self._is_directory(template_dir):
            self.add_error(f"Template path is not a directory: {template_dir}.")
            return
        if not os.access(template_dir, os.R_OK):
            self.add_error(f"Template directory is not readable: {template_dir}.")

    def _validate_output_file_logic(self, output_file: str) -> None:
        """
        Validates that the output file path (and its parent directory) are valid for writing.
        Adds errors if not.
        """
        logger.debug(f"Validating output file path: {output_file}")
        if not output_file: # If output_file is optional and not provided, it's not an error.
            logger.debug("No output file provided for validation, skipping.")
            return

        output_path = Path(output_file)
        output_dir = output_path.parent

        if not self._ensure_path_exists(output_dir):
            self.add_error(f"Output directory for file '{output_file}' does not exist: {output_dir}.")
            return # Cannot check writability if parent doesn't exist
        if not self._is_directory(output_dir):
            self.add_error(f"Parent path for output file '{output_file}' is not a directory: {output_dir}.")
            return

        if not os.access(output_dir, os.W_OK):
            self.add_error(f"Output directory for file '{output_file}' is not writable: {output_dir}.")

        if self._ensure_path_exists(output_path):
            if not self._is_file(output_path):
                 self.add_error(f"Output path '{output_path}' exists but is not a file.")
            elif not os.access(output_path, os.W_OK):
                self.add_error(f"Output file '{output_path}' exists but is not writable.")
        # If output_path does not exist, its parent directory's writability is the main concern.

    def validate(self, data: Any, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Validates render-related parameters.

        Args:
            data: A dictionary potentially containing:
                - "agent_name" (Optional[str]): Name of the agent for path validation.
                - "template_dir" (Optional[Path]): Path to the template directory.
                - "output_file" (Optional[str]): Path to the output file.
            config: Not actively used by this validator.

        Returns:
            bool: True if all specified validations pass, False otherwise.
        """
        self.clear_errors()
        self.clear_warnings()

        if not isinstance(data, dict):
            self.add_error("Validation data must be a dictionary.")
            return False

        has_performed_validation = False

        # Validate agent paths if agent_name is provided
        agent_name = data.get("agent_name")
        if agent_name is not None:
            has_performed_validation = True
            if not isinstance(agent_name, str):
                self.add_error("Data field 'agent_name' must be a string.")
            else:
                self._validate_agent_paths_logic(agent_name)

        # Validate template directory if template_dir is provided
        template_dir = data.get("template_dir")
        if template_dir is not None:
            has_performed_validation = True
            if not isinstance(template_dir, Path):
                self.add_error("Data field 'template_dir' must be a Path object.")
            else:
                self._validate_template_directory_logic(template_dir)

        # Validate output file if output_file is provided
        output_file = data.get("output_file")
        if output_file is not None: # Allow empty string if that means "no output file" vs "validate current dir"
            has_performed_validation = True
            if not isinstance(output_file, str): # Path could also be accepted, then convert to str if needed
                self.add_error("Data field 'output_file' must be a string path.")
            else:
                self._validate_output_file_logic(output_file)
        
        if not has_performed_validation:
            self.add_warning("No validation parameters provided to RenderValidator. No checks performed.")
            # Returning True as no checks failed, but a warning indicates nothing was done.
            # Alternatively, could be an error if at least one check is always expected.

        return not self.has_errors()