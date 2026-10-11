"""Where a project lives does not decide what its actions read.

The walk judged a directory by its absolute path: an upstream was read from the
store only when "staging" appeared nowhere in it, and a staged file was left out
when any directory above it was named "batch". So a project under `staging-env/`
ran its readers on nothing, and one under `batch/` read none of its staged files.
An action that finds no input is skipped and its rows deleted, which made both a
loss of stored output rather than an empty run.
"""

import json
import shutil

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    RECORDS,
    SECOND,
    SECOND_ACTION,
    SOURCE,
    TAG_TOOL,
    WORKFLOW,
)
from tests.integration.test_skipped_reader_drops_stale_rows import (
    RESET_ONLY,
    _add_guard_to,
    _rows,
    _status,
)


@pytest.fixture(params=["staging-env", "batch"])
def chained(tmp_path, monkeypatch, request):
    """The two-action workflow, in a project under a directory named *param*."""
    root = tmp_path / request.param / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    staging.joinpath("pages.json").write_text(
        json.dumps([{"page_content": f"page {i}"} for i in range(RECORDS)])
    )
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + SECOND_ACTION)
    (root / "tools" / WORKFLOW / "tag.py").write_text(TAG_TOOL)
    monkeypatch.chdir(root)
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    return root


def _run(*extra):
    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *extra])
    assert result.exit_code == 0, result.output


def test_every_action_reads_its_input(chained):
    _run("--fresh")

    assert _rows(chained, ACTION) == RECORDS
    assert _rows(chained, SECOND) == RECORDS


def test_a_reset_keeps_the_rows_of_input_that_is_there(chained):
    _run("--fresh")
    _add_guard_to(chained, ACTION, RESET_ONLY)

    _run()

    assert _status(chained, ACTION) == "completed"
    assert _status(chained, SECOND) == "completed"
    assert _rows(chained, ACTION) == RECORDS
    assert _rows(chained, SECOND) == RECORDS
