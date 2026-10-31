"""The required-key pre-flight refusal reads a tool returning `[out]`, a key removed from
`out`, and a `try` whose `except` re-raises, through `agac run` (1510).

A tool returning its dict in a one-element list passed pre-flight with a required key set
only in a branch, then failed each record that did not take it. A tool setting the key in
a `try` whose `except` re-raises was refused, although every record it returns has it.
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
    out = {"label": content}
"""

LIST_OF_ONE = (
    _HEADER
    + """\
    if content == "has items":
        out["items"] = "apple, pear"
    return [out]
"""
)

RE_RAISES = (
    _HEADER
    + """\
    try:
        out["items"] = content.upper()
    except AttributeError:
        raise
    return out
"""
)

REMOVED = (
    _HEADER
    + """\
    out["items"] = content
    del out["items"]
    return out
"""
)


LOOP_SETS_AGAIN = (
    _HEADER
    + """\
    out["items"] = ""
    for word in content.split():
        out["items"] = out.pop("items") + word
    return out
"""
)


def _with_tool(tmp_path, mode: str, tool: str):
    project = _project(tmp_path, mode, 'out = {"label": content}')
    (project / "tools" / WORKFLOW / "produce.py").write_text(tool)
    return project


@pytest.mark.parametrize(
    ("mode", "tool", "says"),
    [
        ("online", LIST_OF_ONE, "line 11 of produce.py, inside an `if`"),
        ("batch", LIST_OF_ONE, "line 11 of produce.py, inside an `if`"),
        ("online", REMOVED, "removes it at line 11 of produce.py"),
    ],
    ids=["set-in-a-branch-of-a-list-online", "set-in-a-branch-of-a-list-batch", "removed-online"],
)
def test_a_required_key_a_return_may_lack_is_refused(tmp_path, mode, tool, says):
    project = _with_tool(tmp_path, mode, tool)

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "producer: output schema requires 'items'" in output, output
    assert says in output, output
    assert _dispositions(project) == [], output


@pytest.mark.parametrize(
    ("mode", "tool"),
    [("online", RE_RAISES), ("batch", RE_RAISES), ("online", LOOP_SETS_AGAIN)],
    ids=[
        "set-in-a-try-whose-except-re-raises-online",
        "set-in-a-try-whose-except-re-raises-batch",
        "loop-removes-and-sets-again-online",
    ],
)
def test_a_key_every_return_carries_runs(tmp_path, mode, tool):
    project = _with_tool(tmp_path, mode, tool)

    result = run_agac(project, "run", "-a", WORKFLOW, "--fresh")
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "output schema requires" not in output, output
    assert _dispositions(project) == ["success", "success"], output
