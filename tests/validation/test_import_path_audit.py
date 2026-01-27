"""
Static audit test for import path consistency.

This test uses AST parsing to scan the codebase and verify that all
`from agent_actions.X import Y` statements resolve to actual modules
in the repository.

Purpose: Catch import path mismatches (e.g., tabular_loader vs tabular) at CI time.
Related: Issue #765 - Systematic audit for attribute naming mismatches
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class UnresolvedImport:
    """Represents an import that doesn't resolve to a real module."""

    module_path: str
    file_path: Path
    line_number: int


REPO_ROOT = Path(__file__).resolve().parents[2]
CODE_ROOT = REPO_ROOT / "agent_actions"


def _iter_python_files(root: Path) -> Iterator[Path]:
    """Iterate over all Python files in a directory tree."""
    for path in root.rglob("*.py"):
        # Skip __pycache__ and other generated files
        if "__pycache__" in str(path):
            continue
        yield path


def _module_path_exists(module_path: str) -> bool:
    """
    Check if a module path resolves to a real file or package.

    For 'agent_actions.workflow.models', checks:
    1. agent_actions/workflow/models.py exists, OR
    2. agent_actions/workflow/models/__init__.py exists
    """
    if not module_path.startswith("agent_actions"):
        # External module, assume it exists
        return True

    # Convert module path to filesystem path
    parts = module_path.split(".")
    fs_path = REPO_ROOT.joinpath(*parts)

    # Check if it's a module file
    if fs_path.with_suffix(".py").exists():
        return True

    # Check if it's a package (directory with __init__.py)
    if fs_path.is_dir() and (fs_path / "__init__.py").exists():
        return True

    return False


def _find_unresolved_imports(root: Path) -> Iterator[UnresolvedImport]:
    """
    Scan Python files for imports that don't resolve to real modules.

    Only checks imports from agent_actions.* since external packages
    are managed by pip/uv.
    """
    for path in _iter_python_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            # Skip files with syntax errors
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue

            # Only check agent_actions imports
            if not node.module or not node.module.startswith("agent_actions"):
                continue

            if not _module_path_exists(node.module):
                yield UnresolvedImport(
                    module_path=node.module,
                    file_path=path,
                    line_number=node.lineno,
                )


def _format_unresolved(unresolved: list[UnresolvedImport]) -> str:
    """Format unresolved imports for readable assertion output."""
    lines = []
    for imp in sorted(unresolved, key=lambda i: (str(i.file_path), i.line_number)):
        rel_path = imp.file_path.relative_to(REPO_ROOT)
        lines.append(f"  {rel_path}:{imp.line_number} -> {imp.module_path}")
    return "\n".join(lines)


def test_all_agent_actions_imports_resolve():
    """
    Verify all agent_actions.* imports resolve to actual modules.

    This test catches bugs like:
    - from agent_actions.loaders.tabular_loader import X
      (should be agent_actions.loaders.tabular)
    - from agent_actions.input.xml_loader import X
      (should be agent_actions.input.xml)
    """
    unresolved = list(_find_unresolved_imports(CODE_ROOT))

    if unresolved:
        report = _format_unresolved(unresolved)
        raise AssertionError(
            f"Found {len(unresolved)} import(s) that don't resolve to actual modules:\n\n"
            f"{report}\n\n"
            f"Check for typos in module paths or renamed modules."
        )


def test_module_resolution_logic():
    """Sanity check that module resolution logic works correctly."""
    # These should exist
    assert _module_path_exists("agent_actions.workflow.models")
    assert _module_path_exists("agent_actions.utils.constants")
    assert _module_path_exists("agent_actions.prompt.context.scope")

    # Packages should resolve
    assert _module_path_exists("agent_actions.workflow")
    assert _module_path_exists("agent_actions.utils")

    # Non-existent modules should not resolve
    assert not _module_path_exists("agent_actions.nonexistent_module")
    assert not _module_path_exists("agent_actions.workflow.fake_file")
