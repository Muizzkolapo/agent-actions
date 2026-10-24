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

What reads the tool is answered again over the file too: every row of it may have
changed, and a row minted by the tool is one no record the retry names leads to.
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

# Reads what roll_up wrote for one record, and logs each summary it is handed.
_FINAL = """\
import json
import os
from pathlib import Path
from typing import Any

from agent_actions import udf_tool


@udf_tool
def roll_final(data: Any, *args) -> list[dict]:
    root = Path(os.environ["ROLL_DIR"])
    summary = str(((data or {}).get("roll_up") or {}).get("summary", ""))
    with open(root / "final.jsonl", "a") as log:
        log.write(json.dumps(summary) + "\\n")
    if (root / "die_below").exists():
        os._exit(9)
    if "alpha" in summary and (root / "fail_final").exists():
        raise RuntimeError("alpha fails below while the flag exists")
    return [{"summary": f"FINAL[{summary}]", "exam_density": "low"}]
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
    if (root / "die").exists() or ((root / "die_on_gamma").exists() and "Page gamma." in pages):
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

_FINAL_ACTION = """\
  - name: finalize
    kind: tool
    dependencies: [roll_up]
    intent: "Finalize"
    schema: file_roll_output
    impl: roll_final
    context_scope: { observe: [roll_up.summary] }
"""

# A record tool, then a batch action, reading what the FILE tool wrote.
TOOL_BELOW = ONLINE + _FINAL_ACTION
BATCH_BELOW = (
    ONLINE
    + """\
  - name: restate
    dependencies: [roll_up]
    intent: "Restate"
    run_mode: batch
    schema: file_roll_output
    prompt: $file_roll.Restate
    context_scope: { observe: [roll_up.summary] }
"""
)

_PROMPTS = """\
{prompt Restate}
Restate this summary verbatim.
## SUMMARY
{{ roll_up.summary }}
```json
{"summary": "...", "exam_density": "high|medium|low"}
```
{end_prompt}
"""

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


def _project(
    tmp_path: Path, config: str, file_tool: str, staged: dict[str, list[str]] = STAGED
) -> Path:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(config)
    staging = workflow / "agent_io" / "staging"
    staging.mkdir(parents=True)
    for name, pages in staged.items():
        (staging / name).write_text(json.dumps([{"page_content": page} for page in pages]))
    tools = root / "tools" / WORKFLOW
    tools.mkdir(parents=True)
    (tools / "roll_flatten.py").write_text(_FLATTEN)
    (tools / "roll_tag.py").write_text(_TAG)
    (tools / "roll_final.py").write_text(_FINAL)
    (tools / "roll_pages.py").write_text(file_tool)
    (root / "schema" / WORKFLOW).mkdir()
    (root / "schema" / WORKFLOW / "file_roll_output.yml").write_text(_SCHEMA)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
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


def _rows(
    project: Path, action: str = "roll_up", *, as_stored: bool = False
) -> dict[str, list[dict]]:
    """Each file's rows, read back as the action below reads them unless *as_stored*."""
    backend = _backend(project)
    read = backend.read_target_for_rewrite if as_stored else backend.read_target
    try:
        return {path: read(action, path) for path in backend.list_target_files(action)}
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


def _logged(project: Path, name: str) -> list:
    log = project / name
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def _handed(project: Path) -> list[list[str]]:
    return _logged(project, "handed.jsonl")


def _finalized(project: Path) -> list[str]:
    """The summaries `finalize` was handed, one per call."""
    return _logged(project, "final.jsonl")


def _failed_then_fixed(project: Path, flag: str = "fail_alpha") -> dict[str, list[dict]]:
    """A run in which alpha fails, then the fault gone; returns what roll_up then held."""
    (project / flag).touch()
    _run(project, "--fresh")
    (project / flag).unlink()
    (project / "handed.jsonl").unlink(missing_ok=True)
    (project / "final.jsonl").unlink(missing_ok=True)
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

    def test_a_resumed_run_hands_the_tool_no_file_it_answered(self, project):
        """Killed inside the tool on the second file, after the first was stored with
        alpha quarantined. Alpha is still failed above, so nothing of the first file
        can reach the tool: the resumed run carries it and runs the second."""
        (project / "fail_alpha").touch()
        (project / "die_on_gamma").touch()
        killed = run_agac(
            project, "run", "-a", WORKFLOW, "-u", "tools", "--fresh", env=_env(project)
        )
        assert killed.returncode != 0, killed.stdout + killed.stderr
        (project / "die_on_gamma").unlink()
        (project / "handed.jsonl").unlink()

        _run(project)

        assert _handed(project) == [["Page gamma.", "Page delta."]]
        rows = _rows(project)
        assert _summaries(rows["pages1.json"]) == [None, "Page beta. (1 of 1)"]
        assert _summaries(rows["pages2.json"]) == ["Page gamma. (1 of 2)", "Page delta. (2 of 2)"]


@pytest.mark.parametrize("one_record", [False, True], ids=["retry", "retry --record"])
def test_a_batch_action_above_changes_nothing(tmp_path, one_record):
    project = _project(tmp_path, BATCH_ABOVE, _ROLL_UP)
    _failed_then_fixed(project)

    _retry(project, *(["--record", _alpha(project)] if one_record else []))

    rows = _rows(project)
    assert _summaries(rows["pages1.json"]) == ["Page alpha. + Page beta."]
    assert _summaries(rows["pages2.json"]) == ["Page delta. + Page gamma."]
    assert _handed(project) == [["Page alpha.", "Page beta."]]


def test_a_file_tool_reading_a_fan_in_rolls_up_the_whole_file(tmp_path):
    """The merged walk visits the other file too, holding no named record, so its
    roll-up is carried and has to come back with everything it had."""
    project = _project(tmp_path, FAN_IN, _ROLL_UP)
    before = _failed_then_fixed(project)["pages2.json"]

    _retry(project)

    rows = _rows(project)
    assert _summaries(rows["pages1.json"]) == ["Page alpha. + Page beta."]
    assert _handed(project) == [["Page alpha.", "Page beta."]]
    after = rows["pages2.json"]
    assert _summaries(after) == ["Page delta. + Page gamma."]
    assert [r["source_guid"] for r in after] == [r["source_guid"] for r in before]
    assert [sorted(r["content"]) for r in after] == [sorted(r["content"]) for r in before]


_REVIEW_ACTION = """\
  - name: roll_up
    kind: hitl
    granularity: File
    dependencies: [flatten]
    intent: "Review the file"
    hitl: { port: 3999, instructions: "Review the summaries", timeout: 5 }
    context_scope: { observe: [flatten.summary, source.page_content] }
"""


def test_a_review_a_retry_reaches_shows_only_the_records_it_names(tmp_path):
    """A review's row belongs to the record reviewed, and the other records of the
    file already hold a reviewer's decision, so only the repaired one is asked."""
    project = _project(
        tmp_path, _DEFAULTS.format(run_mode="online") + _FLATTEN_ACTION + _REVIEW_ACTION, _ROLL_UP
    )
    approve = {**_env(project), "AGAC_HITL_AUTO_APPROVE": "true"}
    (project / "fail_alpha").touch()
    result = run_agac(project, "run", "-a", WORKFLOW, "-u", "tools", "--fresh", env=approve)
    assert result.returncode == 0, result.stdout + result.stderr
    (project / "fail_alpha").unlink()
    reviewed = {
        r["source_guid"]
        for r in _rows(project, as_stored=True)["pages1.json"]
        if r["_state"] == "processed"
    }
    assert len(reviewed) == 1

    retry = run_agac(project, "retry", "-a", WORKFLOW, env=approve)

    output = retry.stdout + retry.stderr
    assert retry.returncode == 0, output
    assert "auto-approving all 1 records" in output
    assert "auto-approving all 2 records" not in output
    after = _rows(project, as_stored=True)["pages1.json"]
    assert [r["_state"] for r in after] == ["processed", "processed"]
    assert reviewed <= {r["source_guid"] for r in after}


class TestWhatReadsTheToolAnswersTheFileAgain:
    """`finalize`, a record tool, reads `roll_up`. A file the retry rewrote at the FILE
    tool is answered again below it whole: no row of it can be carried, since each was
    computed from what the tool wrote before."""

    def test_a_count_is_answered_again_for_every_record_of_the_file(self, tmp_path):
        project = _project(tmp_path, TOOL_BELOW, _COUNT)
        _failed_then_fixed(project)

        _retry(project)

        rows = _rows(project, "finalize")
        assert _summaries(rows["pages1.json"], "finalize") == [
            "FINAL[Page alpha. (1 of 2)]",
            "FINAL[Page beta. (2 of 2)]",
        ]
        assert sorted(_finalized(project)) == ["Page alpha. (1 of 2)", "Page beta. (2 of 2)"]
        assert _summaries(rows["pages2.json"], "finalize") == [
            "FINAL[Page gamma. (1 of 2)]",
            "FINAL[Page delta. (2 of 2)]",
        ]

    def test_a_roll_up_is_answered_again_under_the_identity_it_now_holds(self, tmp_path):
        project = _project(tmp_path, TOOL_BELOW, _ROLL_UP)
        _failed_then_fixed(project)

        _retry(project)

        rows = _rows(project, "finalize")["pages1.json"]
        assert _summaries(rows, "finalize") == ["FINAL[Page alpha. + Page beta.]"]
        assert [r["source_guid"] for r in rows] == [
            r["source_guid"] for r in _rows(project)["pages1.json"]
        ]
        assert _finalized(project) == ["Page alpha. + Page beta."]
        stored = {
            row["source_guid"] for rows in _rows(project, "finalize").values() for row in rows
        }
        assert _successes(project, "finalize") == stored

    def test_a_run_after_the_retry_finds_it_complete_and_whole(self, tmp_path):
        project = _project(tmp_path, TOOL_BELOW, _ROLL_UP)
        _failed_then_fixed(project)
        _retry(project)
        (project / "final.jsonl").unlink(missing_ok=True)

        _run(project)

        assert _finalized(project) == []
        rows = _rows(project, "finalize")["pages1.json"]
        assert _summaries(rows, "finalize") == ["FINAL[Page alpha. + Page beta.]"]

    def test_a_run_finishing_a_retry_that_died_below_the_tool_answers_the_file_again(
        self, tmp_path
    ):
        """The retry dies in `finalize`, after `roll_up` stored the file whole. The plain
        run that follows runs `finalize` alone, and holds beta's answer to the old count."""
        project = _project(tmp_path, TOOL_BELOW, _COUNT)
        _failed_then_fixed(project)
        (project / "die_below").touch()
        killed = run_agac(project, "retry", "-a", WORKFLOW, env=_env(project))
        assert killed.returncode != 0, killed.stdout + killed.stderr
        (project / "die_below").unlink()
        (project / "handed.jsonl").unlink()

        _run(project)

        assert _handed(project) == []
        assert _summaries(_rows(project, "finalize")["pages1.json"], "finalize") == [
            "FINAL[Page alpha. (1 of 2)]",
            "FINAL[Page beta. (2 of 2)]",
        ]

    def test_a_batch_action_below_is_sent_the_file_again(self, tmp_path):
        project = _project(tmp_path, BATCH_BELOW, _ROLL_UP)
        _failed_then_fixed(project)
        before = _rows(project, "restate")["pages2.json"]

        _retry(project)
        _run(project)

        rows = _rows(project, "restate")
        assert [r["source_guid"] for r in rows["pages1.json"]] == [
            r["source_guid"] for r in _rows(project)["pages1.json"]
        ]
        assert [r["_state"] for r in _rows(project, "restate", as_stored=True)["pages1.json"]] == [
            "processed"
        ]
        assert [r["source_guid"] for r in rows["pages2.json"]] == [r["source_guid"] for r in before]


def test_a_record_limit_on_the_roll_up_admits_what_a_run_admits(tmp_path):
    """A roll-up's row names no record, so it says nothing of which records the limit
    admitted when it was written: the retry admits what a run of the same config does,
    and the records it names."""
    config = ONLINE.replace(
        "    granularity: File\n", "    granularity: File\n    record_limit: 2\n"
    )
    staged = {
        "pages1.json": ["Page alpha.", "Page beta.", "Page epsilon.", "Page zeta."],
        "pages2.json": ["Page gamma.", "Page delta."],
    }
    project = _project(tmp_path, config, _ROLL_UP, staged)
    _run(project, "--fresh")
    assert _summaries(_rows(project)["pages1.json"]) == ["Page alpha. + Page beta."]
    _failed_then_fixed(project)

    _retry(project)

    assert _handed(project) == [["Page alpha.", "Page beta."]]
    assert _summaries(_rows(project)["pages1.json"]) == ["Page alpha. + Page beta."]


# One row per record, each computed from that record alone: handed the whole file again,
# the tool writes every row it wrote before exactly as it was.
_PER_RECORD = (
    _FILE_TOOL_HEAD
    + """

@udf_tool(granularity=Granularity.FILE)
def roll_pages(data: list) -> FileUDFResult:
    pages = _handed(data)
    return FileUDFResult(
        outputs=[
            {"source_index": i, "data": {"summary": f"{page} (item)", "exam_density": "low"}}
            for i, page in enumerate(pages)
        ]
    )
"""
)

# One row per record, each computed from that record and the one before it: handed the
# whole file again, the tool writes the row after a record that returned differently,
# and every row further on as it was.
_AFTER_PREVIOUS = (
    _FILE_TOOL_HEAD
    + """

@udf_tool(granularity=Granularity.FILE)
def roll_pages(data: list) -> FileUDFResult:
    pages = _handed(data)
    return FileUDFResult(
        outputs=[
            {
                "source_index": i,
                "data": {
                    "summary": f"{page} after {pages[i - 1] if i else '-'}",
                    "exam_density": "low",
                },
            }
            for i, page in enumerate(pages)
        ]
    )
"""
)

# One row per record, refusing gamma's while `refuse_gamma` exists: the tool itself
# fails one record of a file it is handed again.
_PER_RECORD_REFUSING_GAMMA = (
    _FILE_TOOL_HEAD
    + """

@udf_tool(granularity=Granularity.FILE)
def roll_pages(data: list) -> FileUDFResult:
    pages = _handed(data)
    refuse = (Path(os.environ["ROLL_DIR"]) / "refuse_gamma").exists()
    return FileUDFResult(
        outputs=[
            {
                "source_index": i,
                "data": {
                    "summary": 7 if refuse and "gamma" in page else f"{page} (item)",
                    "exam_density": "low",
                },
            }
            for i, page in enumerate(pages)
        ]
    )
"""
)

# A second FILE tool reading the first: one row per record, counted across the file,
# logging the summaries it is handed.
_COUNT_BELOW_TOOL = """\
import json
import os
from pathlib import Path

from agent_actions import FileUDFResult, udf_tool
from agent_actions.config.schema import Granularity


@udf_tool(granularity=Granularity.FILE)
def roll_count(data: list) -> FileUDFResult:
    root = Path(os.environ["ROLL_DIR"])
    summaries = [str(item.get("summary", "")) for item in data]
    with open(root / "count_handed.jsonl", "a") as log:
        log.write(json.dumps(summaries) + "\\n")
    return FileUDFResult(
        outputs=[
            {
                "source_index": i,
                "data": {"summary": f"{s} [{i + 1} of {len(summaries)}]", "exam_density": "low"},
            }
            for i, s in enumerate(summaries)
        ]
    )
"""

COUNT_BELOW = (
    ONLINE
    + """\
  - name: roll_count
    kind: tool
    granularity: File
    dependencies: [roll_up]
    intent: "Count"
    schema: file_roll_output
    impl: roll_count
    context_scope: { observe: [roll_up.summary] }
"""
)

# A record tool splitting each record in two, above the FILE tool.
_FLATTEN_SPLIT = _FLATTEN.replace(
    '    return [{"summary": page, "exam_density": "low"}]',
    "    return [\n"
    '        {"summary": page + " #1", "exam_density": "low"},\n'
    '        {"summary": page + " #2", "exam_density": "low"},\n'
    "    ]",
)

# Reads what finalize wrote for one record, and logs each summary it is handed.
_GRAND = """\
import json
import os
from pathlib import Path
from typing import Any

from agent_actions import udf_tool


@udf_tool
def roll_grand(data: Any, *args) -> list[dict]:
    root = Path(os.environ["ROLL_DIR"])
    summary = str(((data or {}).get("finalize") or {}).get("summary", ""))
    with open(root / "grand.jsonl", "a") as log:
        log.write(json.dumps(summary) + "\\n")
    return [{"summary": f"GRAND[{summary}]", "exam_density": "low"}]
"""

GRANDCHILD_BELOW = (
    TOOL_BELOW
    + """\
  - name: grand
    kind: tool
    dependencies: [finalize]
    intent: "Grand"
    schema: file_roll_output
    impl: roll_grand
    context_scope: { observe: [finalize.summary] }
"""
)


def _by_guid(rows: list[dict]) -> dict[str, dict]:
    return {row["source_guid"]: row for row in rows if row.get("source_guid")}


class TestARowTheToolWritesAgainUnchangedIsCarriedBelow:
    """The tool is handed the whole file again, and writes beta's row exactly as it was.
    What reads the tool holds an answer computed from that row, so it stands: only
    alpha, whose row the tool wrote for the first time, is answered again below."""

    @pytest.fixture
    def project(self, tmp_path):
        return _project(tmp_path, TOOL_BELOW, _PER_RECORD)

    def test_the_premise_the_tool_is_handed_the_whole_file_again(self, project):
        _failed_then_fixed(project)

        _retry(project)

        assert _handed(project) == [["Page alpha.", "Page beta."]]
        assert _summaries(_rows(project)["pages1.json"]) == [
            "Page alpha. (item)",
            "Page beta. (item)",
        ]

    def test_only_the_record_whose_row_changed_is_answered_again_below(self, project):
        _failed_then_fixed(project)

        _retry(project)

        assert _finalized(project) == ["Page alpha. (item)"]
        assert _summaries(_rows(project, "finalize")["pages1.json"], "finalize") == [
            "FINAL[Page alpha. (item)]",
            "FINAL[Page beta. (item)]",
        ]

    def test_the_row_written_again_unchanged_is_the_row_it_was(self, project):
        _failed_then_fixed(project)
        before = _by_guid(_rows(project, as_stored=True)["pages1.json"])
        (beta,) = [guid for guid, row in before.items() if row["_state"] == "processed"]

        _retry(project)

        after = _by_guid(_rows(project, as_stored=True)["pages1.json"])
        assert after[beta]["target_id"] == before[beta]["target_id"]
        assert after[beta]["node_id"] == before[beta]["node_id"]
        assert after[beta]["content"] == before[beta]["content"]
        alpha = next(guid for guid in after if guid != beta)
        assert after[alpha]["_state"] == "processed"
        assert after[alpha]["target_id"] != before[alpha]["target_id"]

    def test_the_answer_below_still_names_the_row_it_was_computed_from(self, project):
        _failed_then_fixed(project)
        before = _by_guid(_rows(project, "finalize", as_stored=True)["pages1.json"])
        (beta,) = [guid for guid, row in before.items() if row["_state"] == "processed"]

        _retry(project)

        roll_up = _by_guid(_rows(project, as_stored=True)["pages1.json"])
        finalize = _by_guid(_rows(project, "finalize", as_stored=True)["pages1.json"])
        assert finalize[beta]["target_id"] == before[beta]["target_id"]
        assert finalize[beta]["parent_target_id"] == roll_up[beta]["target_id"]

    def test_every_stored_row_below_is_vouched_for(self, project):
        _failed_then_fixed(project)

        _retry(project)

        stored = {
            row["source_guid"] for rows in _rows(project, "finalize").values() for row in rows
        }
        assert _successes(project, "finalize") == stored

    def test_a_run_after_the_retry_finds_it_complete_and_whole(self, project):
        _failed_then_fixed(project)
        _retry(project)
        (project / "handed.jsonl").unlink(missing_ok=True)
        (project / "final.jsonl").unlink(missing_ok=True)

        _run(project)

        assert _handed(project) == []
        assert _finalized(project) == []
        assert _summaries(_rows(project, "finalize")["pages1.json"], "finalize") == [
            "FINAL[Page alpha. (item)]",
            "FINAL[Page beta. (item)]",
        ]

    def test_a_changed_row_of_a_record_the_retry_did_not_name_is_answered_again_below(
        self, tmp_path
    ):
        """Alpha returning changes beta's row, which the retry did not name and which
        holds a success below; gamma's row is as it was. Below, beta is answered again
        with alpha, and gamma alone is carried."""
        staged = {"pages1.json": ["Page alpha.", "Page beta.", "Page gamma."]}
        project = _project(tmp_path, TOOL_BELOW, _AFTER_PREVIOUS, staged)
        _failed_then_fixed(project)
        before = _by_guid(_rows(project, "finalize", as_stored=True)["pages1.json"])
        assert _summaries(list(before.values()), "finalize") == [
            None,
            "FINAL[Page beta. after -]",
            "FINAL[Page gamma. after Page beta.]",
        ]
        (gamma,) = [
            guid
            for guid, row in before.items()
            if _summaries([row], "finalize") == ["FINAL[Page gamma. after Page beta.]"]
        ]

        _retry(project)

        assert sorted(_finalized(project)) == [
            "Page alpha. after -",
            "Page beta. after Page alpha.",
        ]
        after = _by_guid(_rows(project, "finalize", as_stored=True)["pages1.json"])
        assert _summaries(list(after.values()), "finalize") == [
            "FINAL[Page alpha. after -]",
            "FINAL[Page beta. after Page alpha.]",
            "FINAL[Page gamma. after Page beta.]",
        ]
        assert after[gamma]["target_id"] == before[gamma]["target_id"]
        assert _successes(project, "finalize") == set(after)

    def test_a_file_tool_below_counts_the_file_again_when_the_tool_fails_a_record_anew(
        self, tmp_path
    ):
        """Alpha still fails above, and the tool now refuses gamma: beta's row is as it
        was, but the file below holds one record where it held two, so the FILE tool
        below is handed it again rather than carrying a count of two."""
        staged = {"pages1.json": ["Page alpha.", "Page beta.", "Page gamma."]}
        project = _project(tmp_path, COUNT_BELOW, _PER_RECORD_REFUSING_GAMMA, staged)
        (project / "tools" / WORKFLOW / "roll_count.py").write_text(_COUNT_BELOW_TOOL)
        (project / "fail_alpha").touch()
        _run(project, "--fresh")
        assert _summaries(_rows(project, "roll_count")["pages1.json"], "roll_count") == [
            None,
            "Page beta. (item) [1 of 2]",
            "Page gamma. (item) [2 of 2]",
        ]
        (project / "count_handed.jsonl").unlink()
        (project / "refuse_gamma").touch()

        result = run_agac(project, "retry", "-a", WORKFLOW, env=_env(project))

        assert result.returncode == 0, result.stdout + result.stderr
        assert _logged(project, "count_handed.jsonl") == [["Page beta. (item)"]]
        # Quarantined rows first, as FILE mode writes a file.
        assert _summaries(_rows(project, "roll_count")["pages1.json"], "roll_count") == [
            None,
            None,
            "Page beta. (item) [1 of 1]",
        ]

    def test_the_children_of_a_record_split_above_the_tool_are_carried_below(self, tmp_path):
        """A record split in two above the tool names its ancestor as parent; each child's
        row the tool writes again unchanged is carried below all the same."""
        project = _project(tmp_path, TOOL_BELOW, _PER_RECORD)
        (project / "tools" / WORKFLOW / "roll_flatten.py").write_text(_FLATTEN_SPLIT)
        _failed_then_fixed(project)

        _retry(project)

        # The tool logs each record's source page, which a record's two children share.
        assert _handed(project) == [["Page alpha.", "Page alpha.", "Page beta.", "Page beta."]]
        assert _finalized(project) == ["Page alpha. (item)", "Page alpha. (item)"]
        assert sorted(_summaries(_rows(project, "finalize")["pages1.json"], "finalize")) == [
            "FINAL[Page alpha. (item)]",
            "FINAL[Page alpha. (item)]",
            "FINAL[Page beta. (item)]",
            "FINAL[Page beta. (item)]",
        ]

    def test_a_row_the_tool_writes_differently_is_answered_again_below(self, tmp_path):
        """The positive control: a count across the file changes beta's row too."""
        project = _project(tmp_path, TOOL_BELOW, _COUNT)
        _failed_then_fixed(project)

        _retry(project)

        assert sorted(_finalized(project)) == ["Page alpha. (1 of 2)", "Page beta. (2 of 2)"]

    def test_what_reads_the_file_further_below_carries_the_unchanged_record_too(self, tmp_path):
        project = _project(tmp_path, GRANDCHILD_BELOW, _PER_RECORD)
        (project / "tools" / WORKFLOW / "roll_grand.py").write_text(_GRAND)
        _failed_then_fixed(project)
        (project / "grand.jsonl").unlink(missing_ok=True)

        _retry(project)

        assert _finalized(project) == ["Page alpha. (item)"]
        assert _logged(project, "grand.jsonl") == ["FINAL[Page alpha. (item)]"]
        assert _summaries(_rows(project, "grand")["pages1.json"], "grand") == [
            "GRAND[FINAL[Page alpha. (item)]]",
            "GRAND[FINAL[Page beta. (item)]]",
        ]

    def test_a_batch_action_below_is_sent_only_the_record_whose_row_changed(self, tmp_path):
        project = _project(tmp_path, BATCH_BELOW, _PER_RECORD)
        _failed_then_fixed(project)
        before = _by_guid(_rows(project, "restate", as_stored=True)["pages1.json"])
        (beta,) = [guid for guid, row in before.items() if row["_state"] == "processed"]

        output = _retry(project)
        _run(project)

        assert "submitted: 1 requests" in output, output
        after = _by_guid(_rows(project, "restate", as_stored=True)["pages1.json"])
        assert after[beta]["target_id"] == before[beta]["target_id"]
        assert [row["_state"] for row in after.values()] == ["processed", "processed"]


class TestThePlanSaysWhatAFileToolCosts:
    """A retry reaching a FILE tool hands it the whole file, and what reads the tool may
    answer the file again. The plan says so before anything is cleared."""

    def test_the_plan_names_the_file_tool_and_what_reads_it(self, tmp_path):
        project = _project(tmp_path, GRANDCHILD_BELOW, _PER_RECORD)
        (project / "tools" / WORKFLOW / "roll_grand.py").write_text(_GRAND)
        _failed_then_fixed(project)

        result = run_agac(project, "retry", "-a", WORKFLOW, "--dry-run", env=_env(project))

        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        assert "Dry run" in output
        assert "'roll_up' is a File tool" in output, output
        assert "every record of each file holding a record listed above" in output, output
        assert "what reads it (finalize, grand) answers again" in output, output
        assert "every record whose row it writes differently" in output, output

    def test_the_plan_says_nothing_of_a_file_tool_above_the_retry(self, tmp_path):
        """A retry starting below the tool never reaches it."""
        project = _project(tmp_path, TOOL_BELOW, _PER_RECORD)
        _failed_then_fixed(project, flag="fail_final")

        result = run_agac(project, "retry", "-a", WORKFLOW, "--dry-run", env=_env(project))

        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        assert "From action: finalize" in output, output
        assert "File tool" not in output, output


# Two rows per record, each computed from that record alone: the output expands, so
# every row is minted a new identity on every run.
_EXPANDING = (
    _FILE_TOOL_HEAD
    + """

@udf_tool(granularity=Granularity.FILE)
def roll_pages(data: list) -> FileUDFResult:
    pages = _handed(data)
    return FileUDFResult(
        outputs=[
            {"source_index": i, "data": {"summary": f"{page} part {n}", "exam_density": "low"}}
            for i, page in enumerate(pages)
            for n in (1, 2)
        ]
    )
"""
)

# Two rows per record, the second counted across the file: alpha returning changes
# beta's second row and leaves its first as it was.
_EXPANDING_COUNT = (
    _FILE_TOOL_HEAD
    + """

@udf_tool(granularity=Granularity.FILE)
def roll_pages(data: list) -> FileUDFResult:
    pages = _handed(data)
    return FileUDFResult(
        outputs=[
            row
            for i, page in enumerate(pages)
            for row in (
                {"source_index": i, "data": {"summary": f"{page} part 1", "exam_density": "low"}},
                {
                    "source_index": i,
                    "data": {"summary": f"{page} of {len(pages)}", "exam_density": "low"},
                },
            )
        ]
    )
"""
)


def _row_of(rows: list[dict], action: str, summary: str) -> dict:
    (row,) = [row for row in rows if _summaries([row], action) == [summary]]
    return row


class TestARowAnExpandingToolWritesAgainUnchangedIsCarriedBelow:
    """The tool writes two rows per record, so each row is minted a new identity on
    every run. Handed the whole file again, it writes beta's two rows as they were:
    they are matched to the stored rows through the record they came from, and only
    alpha's rows are answered again below."""

    @pytest.fixture
    def project(self, tmp_path):
        return _project(tmp_path, TOOL_BELOW, _EXPANDING)

    def test_the_premise_the_tool_writes_two_rows_per_record(self, project):
        _failed_then_fixed(project)

        _retry(project)

        assert _handed(project) == [["Page alpha.", "Page beta."]]
        assert sorted(_summaries(_rows(project)["pages1.json"])) == [
            "Page alpha. part 1",
            "Page alpha. part 2",
            "Page beta. part 1",
            "Page beta. part 2",
        ]

    def test_only_the_rows_of_the_record_the_retry_names_are_answered_again_below(self, project):
        _failed_then_fixed(project)

        _retry(project)

        assert sorted(_finalized(project)) == ["Page alpha. part 1", "Page alpha. part 2"]
        assert sorted(_summaries(_rows(project, "finalize")["pages1.json"], "finalize")) == [
            "FINAL[Page alpha. part 1]",
            "FINAL[Page alpha. part 2]",
            "FINAL[Page beta. part 1]",
            "FINAL[Page beta. part 2]",
        ]

    def test_each_row_written_again_unchanged_keeps_the_identity_it_was_stored_under(self, project):
        before = _failed_then_fixed(project)["pages1.json"]
        stored = {
            summary: _row_of(before, "roll_up", summary)
            for summary in ("Page beta. part 1", "Page beta. part 2")
        }

        _retry(project)

        after = _rows(project, as_stored=True)["pages1.json"]
        for summary, was in stored.items():
            now = _row_of(after, "roll_up", summary)
            assert now["source_guid"] == was["source_guid"]
            assert now["target_id"] == was["target_id"]

    def test_every_stored_row_below_is_vouched_for_and_a_run_after_finds_it_whole(self, project):
        _failed_then_fixed(project)
        _retry(project)
        stored = {
            row["source_guid"] for rows in _rows(project, "finalize").values() for row in rows
        }
        assert _successes(project, "finalize") == stored
        rolled = {row["source_guid"] for rows in _rows(project).values() for row in rows}
        assert rolled <= _successes(project)
        (project / "handed.jsonl").unlink(missing_ok=True)
        (project / "final.jsonl").unlink(missing_ok=True)

        _run(project)

        assert _handed(project) == []
        assert _finalized(project) == []

    def test_a_row_of_an_unnamed_record_the_tool_writes_differently_is_answered_again(
        self, tmp_path
    ):
        """The positive control: beta's count changes with alpha back, its first row
        does not; below, beta's count is answered again and its first row is carried."""
        project = _project(tmp_path, TOOL_BELOW, _EXPANDING_COUNT)
        _failed_then_fixed(project)

        _retry(project)

        assert sorted(_finalized(project)) == [
            "Page alpha. of 2",
            "Page alpha. part 1",
            "Page beta. of 2",
        ]

    def test_a_batch_action_below_is_sent_only_the_rows_of_the_record_named(self, tmp_path):
        project = _project(tmp_path, BATCH_BELOW, _EXPANDING)
        _failed_then_fixed(project)

        output = _retry(project)
        _run(project)

        assert "submitted: 2 requests" in output, output
