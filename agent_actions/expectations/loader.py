"""Building a Suite from a schema-path file or an inline list."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_actions.expectations.types import Expectation, Suite


def build_suite_from_schema_data(suite_name: str, data: Any) -> Suite:
    """Build a Suite from the ``expectations:`` block of loaded schema data."""
    if not isinstance(data, dict):
        raise ValueError(
            f"Schema file '{suite_name}' must be a mapping, found {type(data).__name__}"
        )
    entries = data.get("expectations")
    if not entries:
        raise ValueError(f"Schema file '{suite_name}' has no expectations: block")
    return Suite(name=suite_name, expectations=entries)


def load_named_suite(suite_name: str, project_root: Path | None = None) -> Suite:
    """Load a suite by name through the schema route, like ``schema:`` resolves."""
    from agent_actions.output.response.loader import SchemaLoader

    data = SchemaLoader.load_schema(suite_name, project_root=project_root)
    return build_suite_from_schema_data(suite_name, data)


def build_inline_suite(entries: list[dict[str, Any]], action_name: str) -> Suite:
    """Wrap an action's inline ``expectations:`` list as an anonymous suite."""
    return Suite(
        name=f"{action_name}:inline", expectations=[Expectation(**entry) for entry in entries]
    )
