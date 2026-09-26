"""`agac retry` reports a failed repair in its exit code, the way `agac run` does.

The two commands classify the finished workflow identically — complete, terminal
with a failed action, or paused on a batch — and `run` exits 1 on the failed one.
`retry` computed the same answer, recorded it against the run, and then returned
success, so a repair that fixed nothing was indistinguishable from one that worked
to a script, a CI job, or a loop.

What counts as failure is settled by `run` and not re-opened here: a *record* that
failed inside an action that still completed leaves the action
``completed_with_failures``, which both commands call success. A failed *action*
is the non-zero case.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    WORKFLOW,
    _disposition,
    _drop_stored_row,
    _fail,
    _read_first_file,
)

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
PAGES = 3

# The tool reads the marker on every call rather than at import: the fixture has
# already run the workflow once by the time a test decides what should break, and
# rewriting the file then would not be picked up by the cached module.
BREAKABLE_TOOL = """import os
from pathlib import Path
from typing import Any

from agent_actions import udf_tool


@udf_tool
def retry_exit_flatten(data: Any, *args) -> list[dict]:
    text = str(((data or {}).get("source") or {}).get("page_content", ""))
    marker = Path(os.environ.get("RETRY_EXIT_BREAK", os.devnull))
    if marker.is_file() and text in marker.read_text().split(";"):
        raise RuntimeError("the tool blew up on " + text)
    return [{"summary": text, "exam_density": "low"}]
"""

SECOND_ACTION = """  - name: enrich
    kind: tool
    dependencies: [flatten]
    intent: "Tag"
    schema: tool_action_output
    impl: retry_exit_tag
    context_scope: { observe: [flatten.summary] }
    expect: { repair: none }
"""

TAG_TOOL = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def retry_exit_tag(data: Any, *args) -> list[dict]:
    return [{"summary": str((data or {}).get("summary", "")), "exam_density": "high"}]
"""


class Project:
    """A completed run of three records, with a tool that can be made to raise."""

    def __init__(self, root: Path, marker: Path):
        self.root = root
        self.marker = marker

    def break_on(self, *pages: str) -> None:
        self.marker.write_text(";".join(pages))

    def guid(self, page: str) -> str:
        for row in _read_first_file(self.root, ACTION):
            if row["content"]["source"]["page_content"] == page:
                return row["source_guid"]
        raise AssertionError(f"no stored record for {page!r}")

    def mark_failed(self, *pages: str) -> list[str]:
        """Leave each page's record failed with no output — a genuine failure."""
        guids = [self.guid(page) for page in pages]
        for guid in guids:
            _fail(self.root, guid)
            _drop_stored_row(self.root, guid)
        return guids

    def retry(self, *args: str):
        return CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, *args])

    def run(self, *args: str):
        return CliRunner().invoke(cli, ["run", "-a", WORKFLOW, *args])

    def disposition(self, guid: str) -> str | None:
        return _disposition(self.root, guid)

    def add_second_action(self) -> None:
        config = self.root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
        config.write_text(config.read_text().rstrip("\n") + "\n" + SECOND_ACTION)
        (self.root / "tools" / WORKFLOW / "retry_exit_tag.py").write_text(TAG_TOOL)
        assert self.run("--fresh").exit_code == 0


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    staging.joinpath("pages.json").write_text(
        json.dumps([{"page_content": f"page {i}"} for i in range(PAGES)])
    )
    (root / "tools" / WORKFLOW / "flatten.py").unlink()
    (root / "tools" / WORKFLOW / "retry_exit_probe.py").write_text(BREAKABLE_TOOL)
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().replace("impl: flatten_pages", "impl: retry_exit_flatten"))
    marker = tmp_path / "BREAK"
    monkeypatch.setenv("RETRY_EXIT_BREAK", str(marker))
    monkeypatch.chdir(root)
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)

    assert CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"]).exit_code == 0
    return Project(root, marker)


class TestARepairThatFixedNothingIsNotSuccess:
    def test_it_exits_non_zero(self, project):
        guid = project.mark_failed("page 0")[0]
        project.break_on("page 0")

        result = project.retry("--record", guid)

        assert result.exit_code != 0, result.output

    def test_the_record_it_was_asked_to_repair_is_still_failed(self, project):
        """The exit code has to follow the outcome, not merely the command finishing."""
        guid = project.mark_failed("page 0")[0]
        project.break_on("page 0")

        project.retry("--record", guid)

        assert project.disposition(guid) == "failed"

    def test_it_does_not_announce_completion(self, project):
        guid = project.mark_failed("page 0")[0]
        project.break_on("page 0")

        result = project.retry("--record", guid)

        assert "Retry complete." not in result.output

    def test_it_names_the_action_that_failed(self, project):
        guid = project.mark_failed("page 0")[0]
        project.break_on("page 0")

        result = project.retry("--record", guid)

        assert f"Failed actions: {ACTION}" in result.output

    def test_it_names_a_downstream_action_the_failure_skipped(self, project):
        project.add_second_action()
        guid = project.mark_failed("page 0")[0]
        project.break_on("page 0")

        result = project.retry("--record", guid)

        assert "Skipped actions: enrich" in result.output
        assert result.exit_code != 0


class TestItAgreesWithRunOnWhatFailureMeans:
    def test_the_same_broken_state_fails_both_commands(self, project):
        """Parity is the point: a repair loop reads the two exit codes the same way."""
        guid = project.mark_failed("page 0")[0]
        project.break_on(*(f"page {i}" for i in range(PAGES)))

        retried = project.retry("--record", guid)
        ran = project.run("--fresh")

        assert (retried.exit_code == 0) == (ran.exit_code == 0), (retried.output, ran.output)

    def test_a_record_level_failure_inside_a_completed_action_still_exits_zero(self, project):
        """``completed_with_failures`` is success to `run`, so it stays success here."""
        guids = project.mark_failed("page 0", "page 1")
        project.break_on("page 0")

        result = project.retry()

        assert result.exit_code == 0, result.output
        assert [project.disposition(g) for g in guids] == ["failed", "success"]


class TestARepairThatWorkedIsUnchanged:
    def test_it_exits_zero(self, project):
        guid = project.mark_failed("page 0")[0]

        result = project.retry("--record", guid)

        assert result.exit_code == 0, result.output

    def test_it_still_announces_completion(self, project):
        guid = project.mark_failed("page 0")[0]

        assert "Retry complete." in project.retry("--record", guid).output

    def test_it_still_repairs_the_record(self, project):
        guid = project.mark_failed("page 0")[0]

        project.retry("--record", guid)

        assert project.disposition(guid) == "success"

    def test_having_nothing_to_retry_exits_zero(self, project):
        result = project.retry()

        assert result.exit_code == 0, result.output
        assert "Nothing to retry" in result.output

    def test_a_dry_run_exits_zero(self, project):
        guid = project.mark_failed("page 0")[0]
        project.break_on("page 0")

        result = project.retry("--record", guid, "--dry-run")

        assert result.exit_code == 0, result.output
