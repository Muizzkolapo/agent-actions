"""
Static audit test for service and dependency attribute access.

This test uses AST parsing to scan the codebase and verify that attribute
accesses on service containers (services.support, services.core, self.deps)
match the actual dataclass field definitions.

Purpose: Catch attribute naming mismatches at CI time instead of runtime.
Related: Issue #765 - Systematic audit for attribute naming mismatches
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class AttributeAccess:
    """Represents an attribute access found in source code."""

    attribute: str
    file_path: Path
    line_number: int
    container: str  # "support", "core", or "deps"


REPO_ROOT = Path(__file__).resolve().parents[2]
CODE_ROOT = REPO_ROOT / "agent_actions"
WORKFLOW_MODELS = CODE_ROOT / "workflow" / "models.py"
WORKFLOW_EXECUTOR = CODE_ROOT / "workflow" / "executor.py"


def _iter_python_files(root: Path) -> Iterator[Path]:
    """Iterate over all Python files in a directory tree."""
    for path in root.rglob("*.py"):
        # Skip __pycache__ and other generated files
        if "__pycache__" in str(path):
            continue
        yield path


def _extract_dataclass_fields(source_path: Path, class_name: str) -> set[str]:
    """
    Extract field names from a dataclass definition using AST parsing.

    This avoids importing the module (which could have side effects)
    and works with any dataclass definition.
    """
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue

        fields: set[str] = set()
        for item in node.body:
            # Annotated assignment: field_name: Type = value
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                fields.add(item.target.id)
            # Plain assignment (less common in dataclasses)
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        fields.add(target.id)
        return fields

    raise AssertionError(f"Could not find dataclass '{class_name}' in {source_path}")


def _get_attribute_chain(node: ast.AST) -> list[str] | None:
    """
    Build the full attribute chain for an AST node.

    For `self.services.support.batch_service`, returns:
    ['self', 'services', 'support', 'batch_service']
    """
    if not isinstance(node, ast.Attribute):
        return None

    chain: list[str] = []
    current: ast.expr = node

    while isinstance(current, ast.Attribute):
        chain.append(current.attr)
        current = current.value

    if isinstance(current, ast.Name):
        chain.append(current.id)
    else:
        # Complex expression, can't analyze statically
        return None

    return list(reversed(chain))


def _find_service_accesses(root: Path) -> Iterator[AttributeAccess]:
    """
    Scan Python files for service attribute accesses.

    Looks for patterns like:
    - self.services.support.<attribute>
    - self.services.core.<attribute>
    - self.deps.<attribute>
    """
    for path in _iter_python_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            # Skip files with syntax errors
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue

            chain = _get_attribute_chain(node)
            if not chain:
                continue

            # Check for self.services.support.<attr> or self.services.core.<attr>
            if (
                len(chain) >= 4
                and chain[0] == "self"
                and chain[1] == "services"
                and chain[2] in ("support", "core")
            ):
                yield AttributeAccess(
                    attribute=chain[3],
                    file_path=path,
                    line_number=node.lineno,
                    container=chain[2],
                )

            # Check for self.deps.<attr>
            if len(chain) >= 3 and chain[0] == "self" and chain[1] == "deps":
                yield AttributeAccess(
                    attribute=chain[2],
                    file_path=path,
                    line_number=node.lineno,
                    container="deps",
                )


def _format_mismatches(mismatches: list[AttributeAccess]) -> str:
    """Format mismatches for readable assertion output."""
    lines = []
    for access in sorted(mismatches, key=lambda a: (str(a.file_path), a.line_number)):
        rel_path = access.file_path.relative_to(REPO_ROOT)
        lines.append(f"  {rel_path}:{access.line_number} -> {access.container}.{access.attribute}")
    return "\n".join(lines)


def test_service_attribute_accesses_match_dataclass_definitions():
    """
    Verify all service attribute accesses match dataclass field definitions.

    This test catches bugs like:
    - services.support.manifest (should be manifest_manager)
    - services.core.executor (should be agent_executor)
    - self.deps.manager (should be batch_manager)
    """
    # Load dataclass field definitions
    support_fields = _extract_dataclass_fields(WORKFLOW_MODELS, "SupportServices")
    core_fields = _extract_dataclass_fields(WORKFLOW_MODELS, "CoreServices")
    deps_fields = _extract_dataclass_fields(WORKFLOW_EXECUTOR, "ExecutorDependencies")

    allowed_fields = {
        "support": support_fields,
        "core": core_fields,
        "deps": deps_fields,
    }

    # Collect all mismatches
    mismatches: list[AttributeAccess] = []

    for access in _find_service_accesses(CODE_ROOT):
        valid_fields = allowed_fields[access.container]
        if access.attribute not in valid_fields:
            mismatches.append(access)

    # Assert no mismatches found
    if mismatches:
        mismatch_report = _format_mismatches(mismatches)
        pytest_msg = (
            f"Found {len(mismatches)} service attribute access(es) that don't match "
            f"dataclass definitions:\n\n{mismatch_report}\n\n"
            f"Valid fields:\n"
            f"  SupportServices: {sorted(support_fields)}\n"
            f"  CoreServices: {sorted(core_fields)}\n"
            f"  ExecutorDependencies: {sorted(deps_fields)}"
        )
        raise AssertionError(pytest_msg)


def test_dataclass_definitions_are_parseable():
    """Sanity check that we can parse the dataclass definitions."""
    support_fields = _extract_dataclass_fields(WORKFLOW_MODELS, "SupportServices")
    core_fields = _extract_dataclass_fields(WORKFLOW_MODELS, "CoreServices")
    deps_fields = _extract_dataclass_fields(WORKFLOW_EXECUTOR, "ExecutorDependencies")

    # Verify we found reasonable fields
    assert len(support_fields) >= 4, f"Expected at least 4 SupportServices fields, got {support_fields}"
    assert len(core_fields) >= 3, f"Expected at least 3 CoreServices fields, got {core_fields}"
    assert len(deps_fields) >= 4, f"Expected at least 4 ExecutorDependencies fields, got {deps_fields}"

    # Verify known fields exist
    assert "batch_manager" in support_fields
    assert "agent_runner" in core_fields
    assert "skip_evaluator" in deps_fields
