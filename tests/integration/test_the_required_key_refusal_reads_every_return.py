"""The required-key pre-flight refusal reads every `return` of a tool, not only its last,
through `agac run` (1519).

An early `return {"label": ...}` before the required `items` was set passed pre-flight,
then failed each record that took it. An early return of nothing, or a branch that only
raises, hands back no record to validate, so it is not refused.
"""

from __future__ import annotations

import pytest

from tests._support.agac_cli import run_agac
from tests.integration.test_a_required_key_set_only_in_a_branch_is_refused import (
    WORKFLOW,
    _dispositions,
    _project,
)

_HEADER = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def produce(data: Any, *args):
    content = data["source"]["page_content"]
"""

EARLY_LITERAL = (
    _HEADER
    + """\
    if content == "no items":
        return {"label": content}
    return {"label": content, "items": "apple, pear"}
"""
)

EARLY_LIST_OF_ONE = (
    _HEADER
    + """\
    if content == "no items":
        return [{"label": content}]
    return [{"label": content, "items": "apple, pear"}]
"""
)

EARLY_NAME = (
    _HEADER
    + """\
    out = {"label": content}
    if content == "no items":
        return out
    out["items"] = "apple, pear"
    return out
"""
)

NOTHING_OR_RAISE = (
    _HEADER
    + """\
    if content is None:
        return None
    if not isinstance(content, str):
        raise TypeError("page_content must be text")
    if content == "":
        return []
    out = {"label": content}
    out["items"] = content.upper()
    return out
"""
)


def _with_tool(tmp_path, mode: str, tool: str):
    project = _project(tmp_path, mode, 'out = {"label": content}')
    tools = project / "tools" / WORKFLOW
    (tools / "produce.py").unlink()
    (tools / "fix1519b_every_return.py").write_text(tool)
    return project


@pytest.mark.parametrize("mode", ["online", "batch"])
@pytest.mark.parametrize("tool", [EARLY_LITERAL, EARLY_LIST_OF_ONE], ids=["dict", "list_of_one"])
def test_an_early_return_without_a_required_key_is_refused(tmp_path, mode, tool):
    project = _with_tool(tmp_path, mode, tool)

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "producer: output schema requires 'items'" in output, output
    assert "returns without it at line 10 of fix1519b_every_return.py, inside an `if`" in output
    assert _dispositions(project) == [], output


def test_an_early_return_of_the_dict_before_the_key_is_set_is_refused(tmp_path):
    project = _with_tool(tmp_path, "online", EARLY_NAME)

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "producer: output schema requires 'items'" in output, output
    assert "returns without it at line 11 of fix1519b_every_return.py, inside an `if`" in output
    assert _dispositions(project) == [], output


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_an_early_return_of_nothing_or_a_raising_branch_runs(tmp_path, mode):
    project = _with_tool(tmp_path, mode, NOTHING_OR_RAISE)

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "output schema requires" not in output, output
    assert _dispositions(project) == ["success", "success"], output
