"""Every top-level key the framework reads off a workflow file is declared.

An undeclared one makes every workflow using it fail to load while the suite stays
green, because no fixture writes it yet. Both keys this branch had to add were found
by hand — one is reached through a `getattr` rebinding a grep misses.

Recognises the dict by the names it is held under, so a module holding one under some
other name, or reading it across a function boundary, is invisible. Both boundaries
are pinned by `test_the_shape_the_scan_admits_it_does_not_follow`.
"""

import ast
from pathlib import Path

import pytest

from agent_actions.config.schema import WorkflowConfig

PACKAGE = Path(__file__).resolve().parents[3] / "agent_actions"


def _workflow_dict_names(tree: ast.AST) -> set[str]:
    """Locals bound to a workflow config dict, however they were reached."""
    bound: set[str] = set(WHOLE_FILE_NAMES)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        elif isinstance(node, ast.NamedExpr):
            targets, value = [node.target], node.value
        else:
            continue
        if not _reaches_user_config(value):
            continue
        for target in targets:
            name = _bindable_name(target)
            if name:
                bound.add(name)
    return bound


def _bindable_name(target: ast.AST) -> str | None:
    """`x = ...` and `self._raw = ...` both bind something later read by `.get`."""
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


# What a whole workflow file is called where it is held. Deliberately not
# `agent_config`, which is one action's dict — matching it would read this
# invariant against ActionConfig's fields.
WHOLE_FILE_NAMES = {"user_config", "workflow_config"}


def _reaches_user_config(value: ast.AST) -> bool:
    """Whether an expression evaluates to the whole workflow dict.

    Recognised by name: it is a plain dict everywhere it is held, so there is
    nothing else to recognise it by. Covers an attribute, a bare name, a getattr,
    and any of those wrapped in the `or {}` a tidy-up naturally adds.
    """
    if isinstance(value, ast.BoolOp):
        return any(_reaches_user_config(v) for v in value.values)
    if isinstance(value, ast.Attribute):
        return value.attr in WHOLE_FILE_NAMES
    if isinstance(value, ast.Name):
        return value.id in WHOLE_FILE_NAMES
    if isinstance(value, ast.Call):
        if (
            isinstance(value.func, ast.Name)
            and value.func.id == "getattr"
            and len(value.args) >= 2
            and isinstance(value.args[1], ast.Constant)
            and value.args[1].value in WHOLE_FILE_NAMES
        ):
            return True
    return False


def _is_workflow_dict(node: ast.AST, bound: set[str]) -> bool:
    if _reaches_user_config(node):
        return True
    if isinstance(node, ast.Attribute) and node.attr in bound:
        return True
    return isinstance(node, ast.Name) and node.id in bound


def _label(path: Path) -> str:
    """Repo-relative where possible; the scan is also run over throwaway files."""
    try:
        return str(path.relative_to(PACKAGE.parent))
    except ValueError:
        return str(path)


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
            found.add((key, node.lineno, _label(path)))
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
    files_by_key: dict[str, set[str]] = {}
    for key, _line, file in reads:
        files_by_key.setdefault(key, set()).add(file)

    assert "tool_path" in files_by_key, "plain `self.user_config.get(...)` read not found"
    assert "storage" in files_by_key, "`getattr(..., 'user_config', ...)` read not followed"
    assert any(f.endswith("coordinator.py") for f in files_by_key["storage"])
    # The static analyzer loads a workflow file of its own and is the package's
    # heaviest reader of top-level keys. An earlier version of this scan matched
    # only the name `user_config` and was blind to all of it.
    assert any(f.endswith("workflow_static_analyzer.py") for f in files_by_key["actions"]), (
        "the second entry point that loads a whole workflow file is not covered"
    )
    assert any(f.endswith("schema_service.py") for f in files_by_key["name"])


def test_every_key_read_off_a_workflow_file_is_declared_on_the_model(reads):
    declared = set(WorkflowConfig.model_fields)
    undeclared = sorted(
        f"{file}:{line} reads '{key}'" for key, line, file in reads if key not in declared
    )

    assert not undeclared, (
        "these modules read a top-level workflow key the schema does not declare, so "
        "any workflow using one fails to load:\n  " + "\n  ".join(undeclared)
    )


CAUGHT = {
    "direct": 'cfg = self.user_config\ncfg.get("stray")',
    "attribute target": 'self._raw = getattr(m, "user_config", None) or {}\nself._raw.get("stray")',
    "inline or-default": '(getattr(m, "user_config", None) or {}).get("stray")',
    "plain attribute read": 'self.user_config.get("stray")',
    "subscript": 'self.user_config["stray"]',
    "the analyzer's own name": 'self.workflow_config.get("stray")',
    "parameter of that name": 'def f(workflow_config):\n    return workflow_config.get("stray")',
    "annotated binding": 'cfg: dict = self.user_config\ncfg.get("stray")',
    "chained binding": 'a = b = self.user_config\nb.get("stray")',
    "walrus": 'if (cfg := self.user_config):\n    cfg.get("stray")',
}
MISSED = {
    "crosses a function boundary": 'def helper(cfg):\n    return cfg.get("stray")\nhelper(self.user_config)',
    "held under some other name": 'self.raw = load()\nself.raw.get("stray")',
}


@pytest.mark.parametrize("source", CAUGHT.values(), ids=list(CAUGHT))
def test_the_shapes_the_scan_follows(tmp_path, source):
    """Each of these reaches the workflow dict, and two of them evaded an earlier
    version of this scan."""
    module = tmp_path / "m.py"
    module.write_text(source + "\n")

    assert "stray" in {key for key, _line, _file in _keys_read(module)}


@pytest.mark.parametrize("source", MISSED.values(), ids=list(MISSED))
def test_the_shape_the_scan_admits_it_does_not_follow(tmp_path, source):
    """Pinned so the docstring's stated gap stays true rather than drifting into a
    claim. Closing it needs interprocedural analysis; this records the boundary."""
    module = tmp_path / "m.py"
    module.write_text(source + "\n")

    assert "stray" not in {key for key, _line, _file in _keys_read(module)}
