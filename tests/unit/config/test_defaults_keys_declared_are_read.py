"""Every key `DefaultsConfig` declares is read back out of a defaults block.

The containment in the other direction is pinned next door. This is the side a
schema check cannot cover on its own: a declared key passes validation by
definition, so a workflow can set it, load clean, and get nothing.

Recognises the block by the names it is held under and by the read that produces
it, so a module holding one under some other name, or reading it across a
function boundary, is invisible — the same boundary the workflow-key scan states.
"""

import ast
from pathlib import Path

import pytest

from agent_actions.config.schema import DefaultsConfig
from agent_actions.output.response.config_fields import SIMPLE_CONFIG_FIELDS

PACKAGE = Path(__file__).resolve().parents[3] / "agent_actions"

# What the expander and its helpers call the block they were handed.
DEFAULTS_NAMES = {"defaults"}

# Whole-workflow dicts, as `test_workflow_keys_read_are_declared` names them.
WORKFLOW_NAMES = {"user_config", "workflow_config", "action_config", "config"}


def _is_defaults_read(value: ast.AST) -> bool:
    """Whether an expression evaluates to a workflow's defaults block."""
    if isinstance(value, ast.BoolOp):
        return any(_is_defaults_read(v) for v in value.values)
    if isinstance(value, ast.Call):
        func = value.func
        return (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and bool(value.args)
            and isinstance(value.args[0], ast.Constant)
            and value.args[0].value == "defaults"
            and _names_a_workflow(func.value)
        )
    if isinstance(value, ast.Subscript):
        return (
            isinstance(value.slice, ast.Constant)
            and value.slice.value == "defaults"
            and _names_a_workflow(value.value)
        )
    return False


def _names_a_workflow(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr in WORKFLOW_NAMES or _names_a_workflow(node.value)
    if isinstance(node, ast.Name):
        return node.id in WORKFLOW_NAMES
    return False


def _defaults_names(tree: ast.AST) -> set[str]:
    """Names holding a workflow defaults block in this module.

    A module that binds the bare name to something else — `ActionConfig` has an
    unrelated `defaults` field, for per-field UDF defaults — loses the seed, so
    its reads cannot vouch for a key that nothing else reads.
    """
    genuine: set[str] = set()
    rebound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        elif isinstance(node, ast.NamedExpr):
            targets, value = [node.target], node.value
        else:
            continue
        names = {n for n in (_bindable_name(t) for t in targets) if n}
        (genuine if _is_defaults_read(value) else rebound).update(names)
    return (set(DEFAULTS_NAMES) | genuine) - (rebound - genuine)


def _bindable_name(target: ast.AST) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _is_defaults(node: ast.AST, bound: set[str]) -> bool:
    if _is_defaults_read(node):
        return True
    if isinstance(node, ast.Attribute):
        return node.attr in bound
    return isinstance(node, ast.Name) and node.id in bound


def _label(path: Path) -> str:
    try:
        return str(path.relative_to(PACKAGE.parent))
    except ValueError:
        return str(path)


def _keys_read(path: Path) -> set[tuple[str, int, str]]:
    tree = ast.parse(path.read_text())
    bound = _defaults_names(tree)
    found: set[tuple[str, int, str]] = set()
    for node in ast.walk(tree):
        key = None
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"get", "pop"}
            and _is_defaults(node.func.value, bound)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            key = node.args[0].value
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Load)
            and _is_defaults(node.value, bound)
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
    """Guard on the guard: a walk that matched nothing would pass the real
    assertion for the wrong reason. One read of each shape must be present."""
    files_by_key: dict[str, set[str]] = {}
    for key, _line, file in reads:
        files_by_key.setdefault(key, set()).add(file)

    assert any(f.endswith("expander.py") for f in files_by_key.get("granularity", ())), (
        "the expander's own `defaults.get(...)` reads were not followed"
    )
    assert any(
        f.endswith("expander_action_types.py") for f in files_by_key.get("hitl_timeout", ())
    ), "a read through a parameter named `defaults` was not followed"
    assert any(f.endswith("service_init.py") for f in files_by_key.get("data_source", ())), (
        "a read through a local bound from `user_config.get('defaults')` was not followed"
    )


def test_every_declared_key_is_read_back_out_of_a_defaults_block(reads):
    """A key here that nothing reads is accepted and then dropped, which no
    schema check can detect — a declared key passes validation by definition."""
    # inherit_simple_fields iterates this set and reads each name off the block,
    # so those reads are real without appearing as a constant key anywhere.
    read = {key for key, _line, _file in reads} | set(SIMPLE_CONFIG_FIELDS)
    never_read = sorted(set(DefaultsConfig.model_fields) - read)

    assert not never_read, (
        "these keys are declared on DefaultsConfig and read from nowhere, so a "
        "workflow setting one loads clean and gets nothing: " + ", ".join(never_read)
    )


CAUGHT = {
    "parameter of that name": 'def f(defaults):\n    return defaults.get("stray")',
    "bound from the workflow dict": 'd = user_config.get("defaults") or {}\nd.get("stray")',
    "subscripted off the workflow dict": 'd = workflow_config["defaults"]\nd.get("stray")',
    "attribute target": 'self._d = self.user_config.get("defaults")\nself._d.get("stray")',
    "read straight off the workflow dict": 'user_config.get("defaults").get("stray")',
    "subscript read": 'def f(defaults):\n    return defaults["stray"]',
}
MISSED = {
    "crosses a function boundary": 'def helper(d):\n    return d.get("stray")\nhelper(defaults)',
    "held under some other name": 'blk = load()\nblk.get("stray")',
    # `defaults` also names an action's per-field UDF defaults. A module binding
    # it to one of those must not vouch for a key nothing else reads.
    "the name rebound to another block": 'defaults = action.get("defaults")\ndefaults.get("stray")',
}


@pytest.mark.parametrize("source", CAUGHT.values(), ids=list(CAUGHT))
def test_the_shapes_the_scan_follows(tmp_path, source):
    module = tmp_path / "m.py"
    module.write_text(source + "\n")

    assert "stray" in {key for key, _line, _file in _keys_read(module)}


@pytest.mark.parametrize("source", MISSED.values(), ids=list(MISSED))
def test_the_shape_the_scan_admits_it_does_not_follow(tmp_path, source):
    """Pinned so the docstring's stated gap stays a boundary rather than drifting
    into a claim the scan cannot back."""
    module = tmp_path / "m.py"
    module.write_text(source + "\n")

    assert "stray" not in {key for key, _line, _file in _keys_read(module)}
