"""A FILE tool a retry reaches runs over its whole file, and replaces what the file held.

A `granularity: File` tool is handed every record of a file at once, so each row it
writes can depend on all of them: a roll-up over the file, or a count across it. A
retry names records, and narrowed the tool's input to them, carrying every other row
the file held. The tool rolled up the repaired record alone beside the roll-up the
first run made without it, or counted one record where the file holds two, and the
retry reported success over both.

Each run is its own `agac` process. Two staged files, `pages1.json` (alpha, beta) and
`pages2.json` (gamma, delta); the record tool above fails alpha while a flag file
exists, which is the fault a retry repairs.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "file_roll"
STAGED = {
    "pages1.json": ["Page alpha.", "Page beta."],
    "pages2.json": ["Page gamma.", "Page delta."],
}

_SCHEMA = """\
name: file_roll_output
fields:
  - id: summary
    type: string
  - id: exam_density
    type: string
additionalProperties: true
"""

# Module names no other fixture uses: discovery imports tools by module name.
_FLATTEN = """\
import os
from pathlib import Path
from typing import Any

from agent_actions import udf_tool


@udf_tool
def roll_flatten(data: Any, *args) -> list[dict]:
    page = str(((data or {}).get("source") or {}).get("page_content", ""))
    if "alpha" in page and (Path(os.environ["ROLL_DIR"]) / "fail_alpha").exists():
        raise RuntimeError("alpha fails while the flag exists")
    return [{"summary": page, "exam_density": "low"}]
"""

_TAG = """\
from typing import Any

from agent_actions import udf_tool


@udf_tool
def roll_tag(data: Any, *args) -> list[dict]:
    return [{"summary": "tagged", "exam_density": "high"}]
"""

_FILE_TOOL_HEAD = """\
import json
import os
from pathlib import Path

from agent_actions import FileUDFResult, udf_tool
from agent_actions.config.schema import Granularity


def _handed(data):
    root = Path(os.environ["ROLL_DIR"])
    pages = [item.get("page_content") for item in data]
    with open(root / "handed.jsonl", "a") as log:
        log.write(json.dumps(pages) + "\\n")
    if (root / "die").exists():
        os._exit(9)
    return pages
"""

# One row for the file, which no single record produced.
_ROLL_UP = (
    _FILE_TOOL_HEAD
    + """

@udf_tool(granularity=Granularity.FILE)
def roll_pages(data: list) -> FileUDFResult:
    pages = sorted(_handed(data))
    return FileUDFResult(
        outputs=[
            {
                "source_index": None,
                "data": {"summary": " + ".join(pages), "exam_density": "low"},
            }
        ]
    )
"""
)

# One row per record, each computed across the file. While `refuse_alpha` exists the
# row for alpha breaks the schema, so the tool itself fails that one record.
_COUNT = (
    _FILE_TOOL_HEAD
    + """

@udf_tool(granularity=Granularity.FILE)
def roll_pages(data: list) -> FileUDFResult:
    pages = _handed(data)
    refuse = (Path(os.environ["ROLL_DIR"]) / "refuse_alpha").exists()
    return FileUDFResult(
        outputs=[
            {
                "source_index": i,
                "data": {
                    "summary": 7 if refuse and "alpha" in page else f"{page} ({i + 1} of {len(pages)})",
                    "exam_density": "low",
                },
            }
            for i, page in enumerate(pages)
        ]
    )
"""
)

_DEFAULTS = """\
name: file_roll
description: "A FILE tool below a record tool"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {run_mode}
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
"""

_FLATTEN_ACTION = """\
  - name: flatten
    kind: tool
    intent: "Flatten"
    schema: file_roll_output
    impl: roll_flatten
    context_scope: { observe: [source.page_content] }
"""

_ROLL_UP_ACTION = """\
  - name: roll_up
    kind: tool
    granularity: File
    dependencies: [flatten]
    intent: "Roll the file up"
    schema: file_roll_output
    impl: roll_pages
    context_scope: { observe: [flatten.summary, source.page_content] }
"""

ONLINE = _DEFAULTS.format(run_mode="online") + _FLATTEN_ACTION + _ROLL_UP_ACTION

# The tools run online whatever the default; the batch action is above them.
BATCH_ABOVE = (
    _DEFAULTS.format(run_mode="batch")
    + """\
  - name: summarize
    intent: "Summarise"
    schema: file_roll_output
    prompt: $p.Summarize
    context_scope: { observe: [source.page_content] }
"""
    + _FLATTEN_ACTION.replace("    intent:", "    dependencies: [summarize]\n    intent:").replace(
        "[source.page_content]", "[source.page_content, summarize.summary]"
    )
    + _ROLL_UP_ACTION
)

# The FILE tool reads two actions, merged into one file per staged file.
FAN_IN = (
    _DEFAULTS.format(run_mode="online")
    + _FLATTEN_ACTION
    + """\
  - name: tag
    kind: tool
    intent: "Tag"
    schema: file_roll_output
    impl: roll_tag
    context_scope: { observe: [source.page_content] }
"""
    + _ROLL_UP_ACTION.replace("[flatten]", "[flatten, tag]").replace(
        "[flatten.summary, source.page_content]",
        "[flatten.summary, tag.exam_density, source.page_content]",
    )
)


def _project(tmp_path: Path, config: str, file_tool: str) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(config)
    staging = workflow / "agent_io" / "staging"
    staging.mkdir(parents=True)
    for name, pages in STAGED.items():
        (staging / name).write_text(json.dumps([{"page_content": page} for page in pages]))
    tools = root / "tools" / WORKFLOW
    tools.mkdir(parents=True)
    (tools / "roll_flatten.py").write_text(_FLATTEN)
    (tools / "roll_tag.py").write_text(_TAG)
    (tools / "roll_pages.py").write_text(file_tool)
    (root / "schema" / WORKFLOW).mkdir()
    (root / "schema" / WORKFLOW / "file_roll_output.yml").write_text(_SCHEMA)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _env(project: Path) -> dict[str, str]:
    return {"ROLL_DIR": str(project), "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"}


def _run(project: Path, *args: str) -> str:
    """`agac run` until nothing is left in flight, returning the last run's output."""
    output = ""
    for _ in range(4):
        result = run_agac(project, "run", "-a", WORKFLOW, "-u", "tools", *args, env=_env(project))
        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        if "run again" not in output:
            return output
        args = tuple(arg for arg in args if arg != "--fresh")
    pytest.fail(f"the workflow never stopped asking to be run again:\n{output}")


def _retry(project: Path, *args: str) -> str:
    result = run_agac(project, "retry", "-a", WORKFLOW, *args, env=_env(project))
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Retry complete." in output, output
    return output


def _backend(project: Path):
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=project
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def _rows(project: Path, action: str = "roll_up") -> dict[str, list[dict]]:
    backend = _backend(project)
    try:
        return {
            path: backend.read_target(action, path) for path in backend.list_target_files(action)
        }
    finally:
        backend.close()


def _summaries(rows: list[dict], action: str = "roll_up") -> list[str | None]:
    return [((row.get("content") or {}).get(action) or {}).get("summary") for row in rows]


def _successes(project: Path, action: str = "roll_up") -> set[str]:
    backend = _backend(project)
    try:
        return {
            row["record_id"]
            for row in backend.get_disposition(action)
            if row["disposition"] == "success"
        }
    finally:
        backend.close()


def _alpha(project: Path) -> str:
    """The identity alpha holds at `flatten`, where it failed."""
    backend = _backend(project)
    try:
        (failed,) = [
            row["record_id"]
            for row in backend.get_disposition("flatten")
            if row["disposition"] == "failed"
        ]
        return failed
    finally:
        backend.close()


def _handed(project: Path) -> list[list[str]]:
    log = project / "handed.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def _failed_then_fixed(project: Path, flag: str = "fail_alpha") -> dict[str, list[dict]]:
    """A run in which alpha fails, then the fault gone; returns what roll_up then held."""
    (project / flag).touch()
    _run(project, "--fresh")
    (project / flag).unlink()
    (project / "handed.jsonl").unlink(missing_ok=True)
    return _rows(project)


class TestARollUpOverTheFile:
    @pytest.fixture
    def project(self, tmp_path):
        return _project(tmp_path, ONLINE, _ROLL_UP)

    def test_the_premise_alpha_is_left_out_of_the_first_roll_up(self, project):
        held = _failed_then_fixed(project)

        assert "Page beta." in _summaries(held["pages1.json"])
        assert _summaries(held["pages2.json"]) == ["Page delta. + Page gamma."]

    def test_the_file_holds_one_roll_up_of_every_record(self, project):
        _failed_then_fixed(project)

        _retry(project)

        assert _summaries(_rows(project)["pages1.json"]) == ["Page alpha. + Page beta."]

    def test_the_tool_is_handed_the_whole_file(self, project):
        _failed_then_fixed(project)

        _retry(project)

        assert _handed(project) == [["Page alpha.", "Page beta."]]

    def test_the_other_file_is_left_as_it_was(self, project):
        before = _failed_then_fixed(project)["pages2.json"]

        _retry(project)

        after = _rows(project)["pages2.json"]
        assert [r["source_guid"] for r in after] == [r["source_guid"] for r in before]
        assert _summaries(after) == ["Page delta. + Page gamma."]

    def test_the_replaced_roll_up_takes_its_disposition_with_it(self, project):
        _failed_then_fixed(project)

        _retry(project)

        stored = {row["source_guid"] for rows in _rows(project).values() for row in rows}
        assert _successes(project) == stored

    def test_no_stored_row_is_reported_unattributable(self, project):
        _failed_then_fixed(project)

        output = _retry(project)

        assert "cannot be attributed" not in output

    def test_a_retry_of_one_record_rolls_up_its_whole_file(self, project):
        _failed_then_fixed(project)

        _retry(project, "--record", _alpha(project))

        assert _summaries(_rows(project)["pages1.json"]) == ["Page alpha. + Page beta."]
        assert _handed(project) == [["Page alpha.", "Page beta."]]

    def test_a_run_after_the_retry_finds_it_complete_and_whole(self, project):
        _failed_then_fixed(project)
        _retry(project)

        _run(project)

        assert _summaries(_rows(project)["pages1.json"]) == ["Page alpha. + Page beta."]


class TestACountAcrossTheFile:
    @pytest.fixture
    def project(self, tmp_path):
        return _project(tmp_path, ONLINE, _COUNT)

    def test_every_row_counts_the_whole_file(self, project):
        _failed_then_fixed(project)

        _retry(project)

        rows = _rows(project)
        assert _summaries(rows["pages1.json"]) == ["Page alpha. (1 of 2)", "Page beta. (2 of 2)"]
        assert _summaries(rows["pages2.json"]) == ["Page gamma. (1 of 2)", "Page delta. (2 of 2)"]

    def test_a_record_the_tool_itself_failed_is_counted_with_the_rest(self, project):
        """A retry starting at the FILE tool, which failed alpha's row alone."""
        held = _failed_then_fixed(project, flag="refuse_alpha")
        assert "Page beta. (2 of 2)" in _summaries(held["pages1.json"])

        _retry(project, "--from", "roll_up")

        assert _summaries(_rows(project)["pages1.json"]) == [
            "Page alpha. (1 of 2)",
            "Page beta. (2 of 2)",
        ]
        assert _handed(project) == [["Page alpha.", "Page beta."]]

    def test_a_run_finishing_an_interrupted_retry_counts_the_whole_file(self, project):
        """The retry dies inside the FILE tool, after `flatten` answered alpha; the
        plain run that follows runs `roll_up`, which the retry left pending."""
        _failed_then_fixed(project)
        (project / "die").touch()
        killed = run_agac(project, "retry", "-a", WORKFLOW, env=_env(project))
        assert killed.returncode != 0, killed.stdout + killed.stderr
        (project / "die").unlink()

        _run(project)

        assert _summaries(_rows(project)["pages1.json"]) == [
            "Page alpha. (1 of 2)",
            "Page beta. (2 of 2)",
        ]


def test_a_batch_action_above_changes_nothing(tmp_path):
    project = _project(tmp_path, BATCH_ABOVE, _ROLL_UP)
    _failed_then_fixed(project)

    _retry(project)

    rows = _rows(project)
    assert _summaries(rows["pages1.json"]) == ["Page alpha. + Page beta."]
    assert _summaries(rows["pages2.json"]) == ["Page delta. + Page gamma."]
    assert _handed(project) == [["Page alpha.", "Page beta."]]


def test_a_file_tool_reading_a_fan_in_rolls_up_the_whole_file(tmp_path):
    project = _project(tmp_path, FAN_IN, _ROLL_UP)
    _failed_then_fixed(project)

    _retry(project)

    rows = _rows(project)
    assert _summaries(rows["pages1.json"]) == ["Page alpha. + Page beta."]
    assert _summaries(rows["pages2.json"]) == ["Page delta. + Page gamma."]
    assert _handed(project) == [["Page alpha.", "Page beta."]]
