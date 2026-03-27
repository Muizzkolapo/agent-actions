"""Path validator for pre-flight validation."""

import os
from pathlib import Path
from typing import Any

from agent_actions.validation.base_validator import BaseValidator
from agent_actions.validation.preflight.error_formatter import (
    PreFlightErrorFormatter,
    ValidationIssue,
)


class PathValidator(BaseValidator):
    """Validates file and directory paths exist and are accessible."""

    def __init__(self) -> None:
        super().__init__()
        self.issues: list[ValidationIssue] = []

    def validate(self, data: Any, config: dict[str, Any] | None = None) -> bool:
        """Validate paths in the provided configuration."""
        self.issues = []

        if not self._prepare_validation(data):
            return self._complete_validation()

        paths = data.get("paths", [])
        path_type = data.get("path_type", "file")
        check_readable = data.get("check_readable", True)
        check_writable = data.get("check_writable", False)
        config = config or {}

        agent_name = config.get("agent_name")
        strict = config.get("strict", True)

        if not paths:
            return self._complete_validation()

        invalid_paths = []
        permission_errors = []

        for path_str in paths:
            if not path_str:
                continue

            path = Path(path_str)

            if not path.exists():
                invalid_paths.append(str(path))
                if strict:
                    self.add_error(f"Path does not exist: {path}")
                else:
                    self.add_warning(f"Path does not exist: {path}")
                continue

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

            if check_readable and not os.access(path, os.R_OK):
                permission_errors.append(str(path))
                self.add_error(f"Path is not readable: {path}")

            if check_writable and not os.access(path, os.W_OK):
                permission_errors.append(str(path))
                self.add_error(f"Path is not writable: {path}")

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

        return self._complete_validation()

    def validate_paths(
        self,
        paths: list[str],
        path_type: str = "file",
        agent_name: str | None = None,
        check_readable: bool = True,
        check_writable: bool = False,
    ) -> bool:
        """Validate paths directly without wrapping in a data dict."""
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
        agent_config: dict[str, Any],
        agent_name: str | None = None,
    ) -> bool:
        """Validate all paths referenced in agent configuration."""
        paths_to_check = []

        for key in ["input_file", "input_path", "source_path"]:
            if path := agent_config.get(key):
                paths_to_check.append((path, "input"))

        for key in ["output_file", "output_path"]:
            if path := agent_config.get(key):
                paths_to_check.append((path, "output"))

        if schema_path := agent_config.get("schema_file"):
            paths_to_check.append((schema_path, "schema"))

        if prompt_path := agent_config.get("prompt_file"):
            paths_to_check.append((prompt_path, "prompt"))

        if tools_path := agent_config.get("tools_path"):
            paths_to_check.append((tools_path, "directory"))

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

    def get_issues(self) -> list[ValidationIssue]:
        """Get the list of validation issues found."""
        return self.issues
