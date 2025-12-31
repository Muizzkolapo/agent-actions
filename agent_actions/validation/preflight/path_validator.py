"""Path validator for pre-flight validation.

Validates that file paths referenced in configuration exist and are accessible
before any LLM processing begins.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_actions.validation.base_validator import BaseValidator
from agent_actions.validation.preflight.error_formatter import (
    PreFlightErrorFormatter,
    ValidationIssue,
)


class PathValidator(BaseValidator):
    """Validates file and directory paths exist and are accessible.

    This validator checks that paths referenced in agent configuration
    (input files, schema files, prompt files, output directories) exist
    and have appropriate permissions.

    Attributes:
        issues: List of ValidationIssue objects found during validation
    """

    def __init__(self) -> None:
        super().__init__()
        self.issues: List[ValidationIssue] = []

    # pylint: disable=too-many-branches
    def validate(self, data: Any, config: Optional[Dict[str, Any]] = None) -> bool:
        """Validate paths in the provided configuration.

        Args:
            data: Dictionary containing:
                - 'paths': List of paths to validate
                - 'path_type': Type of paths ('file', 'directory', 'input', 'output')
                - 'check_readable': If True, check read permission
                - 'check_writable': If True, check write permission
            config: Optional config with:
                - 'agent_name': Name of the agent for error messages
                - 'strict': If True, missing paths are errors (default: True)

        Returns:
            bool: True if all paths are valid, False otherwise
        """
        self.clear_errors()
        self.clear_warnings()
        self.issues = []

        if not isinstance(data, dict):
            self.add_error("Validation data must be a dictionary with 'paths' key.")
            return False

        paths = data.get("paths", [])
        path_type = data.get("path_type", "file")
        check_readable = data.get("check_readable", True)
        check_writable = data.get("check_writable", False)
        config = config or {}

        agent_name = config.get("agent_name")
        strict = config.get("strict", True)

        if not paths:
            return True  # No paths to validate

        invalid_paths = []
        permission_errors = []

        for path_str in paths:
            if not path_str:
                continue

            path = Path(path_str)

            # Check existence
            if not path.exists():
                invalid_paths.append(str(path))
                if strict:
                    self.add_error(f"Path does not exist: {path}")
                else:
                    self.add_warning(f"Path does not exist: {path}")
                continue

            # Check type
            if path_type in ("file", "input", "schema", "prompt"):
                if not path.is_file():
                    invalid_paths.append(str(path))
                    self.add_error(f"Path is not a file: {path}")
                    continue
            elif path_type in ("directory", "output"):
                if not path.is_dir():
                    invalid_paths.append(str(path))
                    self.add_error(f"Path is not a directory: {path}")
                    continue

            # Check permissions
            if check_readable and not os.access(path, os.R_OK):
                permission_errors.append(str(path))
                self.add_error(f"Path is not readable: {path}")

            if check_writable and not os.access(path, os.W_OK):
                permission_errors.append(str(path))
                self.add_error(f"Path is not writable: {path}")

        # Create issues for reporting
        if invalid_paths:
            self.issues.append(
                PreFlightErrorFormatter.create_path_issue(
                    message=f"{len(invalid_paths)} path(s) not found or invalid",
                    invalid_paths=invalid_paths,
                    path_type=path_type,
                    agent_name=agent_name,
                )
            )

        if permission_errors:
            self.issues.append(
                ValidationIssue(
                    message="Permission denied for some paths",
                    issue_type="error",
                    category="path",
                    missing_refs=permission_errors,
                    hint="Check file permissions and try again.",
                    agent_name=agent_name,
                    extra_context={"path_type": path_type},
                )
            )

        return not self.has_errors()

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def validate_paths(
        self,
        paths: List[str],
        path_type: str = "file",
        agent_name: Optional[str] = None,
        check_readable: bool = True,
        check_writable: bool = False,
    ) -> bool:
        """Convenience method to validate paths directly.

        Args:
            paths: List of paths to validate
            path_type: Type of paths ('file', 'directory', etc.)
            agent_name: Optional agent name for error messages
            check_readable: Check read permission
            check_writable: Check write permission

        Returns:
            bool: True if all paths are valid
        """
        data = {
            "paths": paths,
            "path_type": path_type,
            "check_readable": check_readable,
            "check_writable": check_writable,
        }
        config = {"agent_name": agent_name}
        return self.validate(data, config)

    def validate_agent_paths(
        self,
        agent_config: Dict[str, Any],
        agent_name: Optional[str] = None,
    ) -> bool:
        """Validate all paths referenced in agent configuration.

        Extracts and validates paths from:
        - input_file / input_path
        - output_file / output_path
        - schema_file
        - prompt_file
        - tools_path

        Args:
            agent_config: Agent configuration dictionary
            agent_name: Optional agent name for error messages

        Returns:
            bool: True if all paths are valid
        """
        paths_to_check = []

        # Input paths
        for key in ["input_file", "input_path", "source_path"]:
            if path := agent_config.get(key):
                paths_to_check.append((path, "input"))

        # Output paths
        for key in ["output_file", "output_path"]:
            if path := agent_config.get(key):
                paths_to_check.append((path, "output"))

        # Schema paths
        if schema_path := agent_config.get("schema_file"):
            paths_to_check.append((schema_path, "schema"))

        # Prompt paths
        if prompt_path := agent_config.get("prompt_file"):
            paths_to_check.append((prompt_path, "prompt"))

        # Tools path
        if tools_path := agent_config.get("tools_path"):
            paths_to_check.append((tools_path, "directory"))

        # Group by type and validate
        all_valid = True
        for path, path_type in paths_to_check:
            is_writable = path_type == "output"
            if not self.validate_paths(
                [path],
                path_type=path_type,
                agent_name=agent_name,
                check_readable=path_type != "output",
                check_writable=is_writable,
            ):
                all_valid = False

        return all_valid

    def get_issues(self) -> List[ValidationIssue]:
        """Get the list of validation issues found.

        Returns:
            List of ValidationIssue objects
        """
        return self.issues
