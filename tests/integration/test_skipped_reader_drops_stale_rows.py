"""A reader skipped because its upstream holds nothing holds nothing either (1230).

A skip never rewrites the reader's output, so whatever it stored before stands
unless the skip removes it. Rows made from upstream output that no longer exists
are removed; rows made from upstream output a failed run carried are not.

Editing an upstream resets everything that reads it (1215), so only the action
that changes is edited here; the readers are reset by that alone.
"""

import json
import re

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.storage.backend import NODE_LEVEL_RECORD_ID
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    RECORDS,
    SECOND,
    WORKFLOW,
    _backend,
    chained,  # noqa: F401
    project,  # noqa: F401
)

THIRD = "recap"
THIRD_ACTION = f"""  - name: {THIRD}
    kind: tool
    dependencies: [enrich]
    intent: "Recap"
    schema: tool_action_output
    impl: tag_density
    context_scope: {{ observe: [enrich.summary] }}
    expect: {{ repair: none }}
"""

FILTER_ALL = '{ condition: \'source.page_content == "none"\', on_false: "filter" }'
RESET_ONLY = "{ condition: 'true', on_false: \"skip\" }"
MODES = pytest.mark.parametrize("mode", ["sequential", "parallel"])

BROKEN_TOOL = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def flatten_broken(data: Any, *args) -> list[dict]:
    raise RuntimeError("down")
"""


def _config(root):
    return root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"


def _add_guard_to(root, action, guard):
    """Give the named action a guard; editing its config is also what resets it."""
    config = _config(root)
    text = config.read_text()
    start = text.index(f"  - name: {action}\n")
    end = text.find("\n  - name:", start + 1)
    end = len(text) if end == -1 else end + 1
    block, n = re.subn(
        r"(    impl: .*\n)",
        lambda m: f"{m.group(1)}    guard: {guard}\n",
        text[start:end],
        count=1,
    )
    assert n == 1, f"no impl line under {action}"
    config.write_text(text[:start] + block + text[end:])


def _rows(root, action):
    backend = _backend(root)
    try:
        return sum(
            len(backend._read_target_raw(action, path))
            for path in backend.list_target_files(action)
        )
    finally:
        backend.close()


def _status(root, action):
    path = root / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return json.loads(path.read_text())[action]["status"]


def _node_reason(root, action):
    backend = _backend(root)
    try:
        rows = backend.get_disposition(action, record_id=NODE_LEVEL_RECORD_ID)
        return rows[0].get("reason") if rows else None
    finally:
        backend.close()


def _run(*extra):
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *extra])
    assert result.exit_code == 0, result.output
    return result


@MODES
def test_a_reader_skipped_under_an_upstream_that_filtered_everything_keeps_no_rows(
    chained,  # noqa: F811
    mode,
):
    _add_guard_to(chained, ACTION, FILTER_ALL)

    _run("-e", mode)

    assert _rows(chained, ACTION) == 0
    assert _rows(chained, SECOND) == 0
    # The path, not just the outcome: the reader was skipped, not run on nothing.
    assert _status(chained, SECOND) == "skipped"
    assert _node_reason(chained, SECOND) == f"Upstream dependency '{ACTION}' skipped"


def test_a_second_run_keeps_it_empty_and_lifting_the_filter_restores_it(chained):  # noqa: F811
    _add_guard_to(chained, ACTION, FILTER_ALL)
    _run()
    _run()
    assert _rows(chained, SECOND) == 0

    config = _config(chained)
    config.write_text(
        "".join(line for line in config.read_text().splitlines(True) if "guard:" not in line)
    )
    _run()

    assert _rows(chained, ACTION) == RECORDS
    assert _rows(chained, SECOND) == RECORDS
    assert _status(chained, SECOND) == "completed"


def test_the_drop_reaches_a_reader_of_the_reader(chained):  # noqa: F811
    config = _config(chained)
    config.write_text(config.read_text().rstrip("\n") + "\n" + THIRD_ACTION)
    _run("--fresh")
    assert _rows(chained, THIRD) == RECORDS

    _add_guard_to(chained, ACTION, FILTER_ALL)
    _run()

    assert _rows(chained, SECOND) == 0
    assert _rows(chained, THIRD) == 0
    assert _node_reason(chained, THIRD) == f"Upstream dependency '{SECOND}' skipped"


def test_a_reader_whose_own_config_changed_too_keeps_no_rows(chained):  # noqa: F811
    _add_guard_to(chained, ACTION, FILTER_ALL)
    _add_guard_to(chained, SECOND, RESET_ONLY)

    _run()

    assert _rows(chained, SECOND) == 0


def test_a_reader_of_an_upstream_that_failed_but_kept_its_rows_keeps_its_own(chained):  # noqa: F811
    # A new module rather than an edit: a tool module already imported in this
    # process is cached by the loader and would not see the edit.
    (chained / "tools" / WORKFLOW / "broken.py").write_text(BROKEN_TOOL)
    config = _config(chained)
    config.write_text(config.read_text().replace("impl: flatten_pages", "impl: flatten_broken"))
    _add_guard_to(chained, SECOND, RESET_ONLY)

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW])

    assert f"Upstream dependency '{ACTION}' failed" in result.output, result.output
    assert _status(chained, ACTION) == "failed"
    assert _rows(chained, ACTION) == RECORDS
    assert _rows(chained, SECOND) == RECORDS
