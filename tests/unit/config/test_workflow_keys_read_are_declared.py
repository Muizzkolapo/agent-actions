"""Every top-level key the framework reads off a workflow file is declared.

`WorkflowConfig` forbids undeclared top-level keys, so a module that reads one the
model does not declare makes every workflow using that key fail to load — while the
suite stays green, because no fixture writes it yet.

Both keys this rule was written for were found by hand: `tool_path` from the ticket,
and `storage` by a reviewer, after a grep for `user_config.get` missed it. The
coordinator binds the dict through `getattr(config_mgr, "user_config", None)` and
reads it two lines later, so the symbol and the read never share a line. This walks
the AST instead, following the binding.
"""

import ast
from pathlib import Path

import pytest

from agent_actions.config.schema import WorkflowConfig

PACKAGE = Path(__file__).resolve().parents[3] / "agent_actions"


def _workflow_dict_names(tree: ast.AST) -> set[str]:
    """Locals bound to a workflow config dict, however they were reached."""
    bound: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = node.value
        reached = (
            # x = <anything>.user_config
            isinstance(value, ast.Attribute) and value.attr == "user_config"
        ) or (
            # x = getattr(<anything>, "user_config", ...)
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "getattr"
            and len(value.args) >= 2
            and isinstance(value.args[1], ast.Constant)
            and value.args[1].value == "user_config"
        )
        if reached:
            bound.add(target.id)
    return bound


def _is_workflow_dict(node: ast.AST, bound: set[str]) -> bool:
    if isinstance(node, ast.Attribute) and node.attr == "user_config":
        return True
    return isinstance(node, ast.Name) and node.id in bound


def _keys_read(path: Path) -> set[tuple[str, int, str]]:
    """(key, lineno, file) for every literal top-level read in one module."""
    tree = ast.parse(path.read_text())
    bound = _workflow_dict_names(tree)
    found: set[tuple[str, int, str]] = set()
    for node in ast.walk(tree):
        key = None
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and _is_workflow_dict(node.func.value, bound)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            key = node.args[0].value
        elif (
            isinstance(node, ast.Subscript)
            and _is_workflow_dict(node.value, bound)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            key = node.slice.value
        if key is not None:
            found.add((key, node.lineno, str(path.relative_to(PACKAGE.parent))))
    return found


@pytest.fixture(scope="module")
def reads() -> set[tuple[str, int, str]]:
    found: set[tuple[str, int, str]] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        found |= _keys_read(path)
    return found


def test_the_scan_finds_the_reads_it_is_supposed_to_follow(reads):
    """Guard on the guard: an AST walk that silently matched nothing would pass
    the real assertion for the wrong reason. Both shapes must be present — the
    plain attribute read, and the one reached through getattr."""
    by_key = {key: (file, line) for key, line, file in reads}

    assert "tool_path" in by_key, "plain `self.user_config.get(...)` read not found"
    assert "storage" in by_key, "`getattr(..., 'user_config', ...)` read not followed"
    assert by_key["storage"][0].endswith("coordinator.py")


def test_every_key_read_off_a_workflow_file_is_declared_on_the_model(reads):
    declared = set(WorkflowConfig.model_fields)
    undeclared = sorted(
        f"{file}:{line} reads '{key}'" for key, line, file in reads if key not in declared
    )

    assert not undeclared, (
        "these modules read a top-level workflow key the schema does not declare, so "
        "any workflow using one fails to load:\n  " + "\n  ".join(undeclared)
    )
