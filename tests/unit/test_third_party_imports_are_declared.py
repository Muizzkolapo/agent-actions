"""Every third-party package that `agent_actions` imports is declared in pyproject.toml.

A package installed only as another dependency's dependency can vanish when that
dependency changes, and then `agac` fails on import.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _names(requirements: list[str]) -> set[str]:
    return {_normalise(re.split(r"[<>=!~\[;\s]", spec, maxsplit=1)[0]) for spec in requirements}


def _declared() -> set[str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = _names(project["dependencies"])
    for extra in project.get("optional-dependencies", {}).values():
        declared |= _names(extra)
    return declared


def _imported_top_level_modules() -> dict[str, set[str]]:
    imported: dict[str, set[str]] = {}
    for path in (ROOT / "agent_actions").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            else:
                continue
            for module in modules:
                top = module.split(".")[0]
                if top in sys.stdlib_module_names or top in {"agent_actions", "__future__"}:
                    continue
                imported.setdefault(top, set()).add(str(path.relative_to(ROOT)))
    return imported


def _undeclared() -> dict[str, set[str]]:
    declared = _declared()
    distributions = packages_distributions()
    undeclared = {}
    for module, files in _imported_top_level_modules().items():
        # A module of an optional extra that is not installed maps to no distribution.
        owners = {_normalise(d) for d in distributions.get(module, [])} or {_normalise(module)}
        if not owners & declared:
            undeclared[module] = files
    return undeclared


def test_httpx_is_declared():
    assert "httpx" in _declared()


def test_click_and_werkzeug_are_declared():
    assert {"click", "werkzeug"} <= _declared()


def test_no_undeclared_third_party_import():
    assert _undeclared() == {}
