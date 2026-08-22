"""Building a Suite from a file, a project-relative name, or an inline list."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_actions.expectations.types import Expectation, Suite

DEFAULT_EXPECTATIONS_DIR = "expectations"


class SuiteNotFoundError(Exception):
    """Raised when a referenced suite file does not exist."""


def suite_file_path(project_root: Path, workflow: str, suite_name: str) -> Path:
    """Where a named suite lives: ``{expectations_path}/{workflow}/{suite}.yml``."""
    from agent_actions.config.path_config import get_expectations_path

    return Path(project_root) / get_expectations_path(project_root) / workflow / f"{suite_name}.yml"


def load_suite_file(path: Path) -> Suite:
    """Load a suite from a YAML file."""
    path = Path(path)
    if not path.is_file():
        raise SuiteNotFoundError(f"Expectation suite not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(
            f"Expectation suite must be a mapping, found {type(data).__name__}: {path}"
        )
    data.setdefault("name", path.stem)
    return Suite(**data)


def load_named_suite(project_root: Path, workflow: str, suite_name: str) -> Suite:
    """Load a suite by name from the project's expectations folder."""
    return load_suite_file(suite_file_path(project_root, workflow, suite_name))


def build_inline_suite(entries: list[dict[str, Any]], action_name: str) -> Suite:
    """Wrap an action's inline ``expectations:`` list as an anonymous suite."""
    return Suite(
        name=f"{action_name}:inline", expectations=[Expectation(**entry) for entry in entries]
    )
