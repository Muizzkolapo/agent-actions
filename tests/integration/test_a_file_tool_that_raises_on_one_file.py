"""A FILE tool that raises on one file fails that file's records (1298).

A `granularity: File` tool is handed a whole file and answers it as one result, which
names no record. When it raised, the walk logged the file and went on: nothing was
stored for the file and no disposition named any of its records, so the action read
`completed` with exit 0. `agac retry` found nothing to retry and the next run found the
action complete. After an edit the file kept its rows from before it, and under a retry
the repaired record was left with no disposition at all.

Every run is an `agac run` or `agac retry` through the CLI, executor, store and mock
provider. Only the fault is stood in for: while a flag file exists, the tool raises on
the file holding page alpha.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli

SOURCE = Path(__file__).parent / "fixtures" / "expectation_authors"
PAGES = {
    "pages1.json": ["Page alpha.", "Page beta."],
    "pages2.json": ["Page gamma.", "Page delta."],
}
BROKEN_FILE = "pages1.json"
FLAG = "pages1_breaks"
UPSTREAM_FLAG = "alpha_fails_upstream"
ACTION = "roll_up"

# Answers every record of its file with what it read, tagged with what the `tag` file
# says; while the flag file exists, it raises on the file holding page alpha.
ROLL_UP = "roll_up_or_break"
ROLL_UP_TOOL = f"""from pathlib import Path
from typing import Any

from agent_actions import udf_tool
from agent_actions.utils.udf_management.registry import Granularity


@udf_tool(granularity=Granularity.FILE)
def {ROLL_UP}(data: Any, *args) -> list[dict]:
    if Path({FLAG!r}).exists() and any(r.get("page_content") == "Page alpha." for r in data):
        raise RuntimeError("the roll-up of pages1 broke")
    for record in data:
        record["summary"] = Path("tag").read_text() + " " + str(record.get("summary"))
        record["exam_density"] = "low"
    return data
"""

# The record tool above it, which fails page alpha while its own flag file exists.
SHAPE = "shape_page_or_fail"
SHAPE_TOOL = f"""from pathlib import Path
from typing import Any

from agent_actions import udf_tool


@udf_tool
def {SHAPE}(data: Any, *args) -> list[dict]:
    page = data["source"]["page_content"]
    if page == "Page alpha." and Path({UPSTREAM_FLAG!r}).exists():
        raise RuntimeError("the shaping of page alpha failed")
    return [{{"summary": Path("tag").read_text() + " " + page, "exam_density": "low"}}]
"""

ROLL_UP_SCHEMA = """name: roll_up_output
fields:
  - id: summary
    type: string
  - id: exam_density
    type: string
additionalProperties: true
"""

ROLL_UP_ACTION = f"""  - name: {ACTION}
    kind: tool
    granularity: File
    dependencies: [UPSTREAM]
    run_mode: online
    intent: "Roll the file up"
    schema: roll_up_output
    impl: {ROLL_UP}
    context_scope: {{ observe: [UPSTREAM.summary, source.page_content] }}
"""

BELOW_A_TOOL = f"""name: tool_action
description: "A FILE tool reading a record tool"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: flatten
    kind: tool
    intent: "Flatten"
    schema: tool_action_output
    impl: {SHAPE}
    context_scope: {{ observe: [source.page_content] }}
    expect: {{ repair: none }}
{ROLL_UP_ACTION.replace("UPSTREAM", "flatten")}"""

BELOW_AN_LLM = f"""name: batch_field_rules
description: "A FILE tool reading an LLM action"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: RUN_MODE
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: summarize
    intent: "Summarise"
    schema: batch_field_rules_output
    prompt: $p.Summarize
    context_scope: {{ observe: [source.page_content] }}
    expect: {{ repair: none }}
{ROLL_UP_ACTION.replace("UPSTREAM", "summarize")}"""

# (workflow, its config, runs that finish a first pass)
WORKFLOWS = {
    "below_a_tool": ("tool_action", BELOW_A_TOOL, 1),
    "below_online": ("batch_field_rules", BELOW_AN_LLM.replace("RUN_MODE", "online"), 1),
    # The first run submits the batch above the tool; the second collects it.
    "below_batch": ("batch_field_rules", BELOW_AN_LLM.replace("RUN_MODE", "batch"), 2),
}


class _Project:
    def __init__(self, root: Path, workflow: str, passes: int) -> None:
        self.root = root
        self.workflow = workflow
        self.passes = passes

    def run(self, *args: str):
        result = None
        for i in range(self.passes):
            result = CliRunner().invoke(
                cli, ["run", "-a", self.workflow, *(args if i == 0 else ())]
            )
            assert result.exit_code == 0, result.output
        return result

    def retry(self):
        return CliRunner().invoke(cli, ["retry", "-a", self.workflow])

    def breaks(self, on: bool = True, flag: str = FLAG) -> None:
        if on:
            (self.root / flag).touch()
        else:
            (self.root / flag).unlink()

    def tag(self, tag: str) -> None:
        (self.root / "tag").write_text(tag)

    def edit_upstream(self) -> None:
        """An edit that resets the action above the tool, and so the tool."""
        if self.workflow == "tool_action":
            edited = self.root / "schema" / "tool_action" / "tool_action_output.yml"
            before = "  - id: exam_density\n"
            after = before + "    description: How densely the page carries exam material\n"
        else:
            edited = self.root / "prompt_store" / "p.md"
            before = "Summarise the page in one sentence"
            after = "Summarise the page in one short sentence"
        assert before in edited.read_text()
        edited.write_text(edited.read_text().replace(before, after, 1))

    def status(self) -> str:
        io = self.root / "agent_workflow" / self.workflow / "agent_io"
        return json.loads((io / ".agent_status.json").read_text())[ACTION]["status"]

    def _backend(self):
        from agent_actions.config.project_paths import ProjectPathsFactory
        from agent_actions.storage import get_storage_backend

        paths = ProjectPathsFactory.create_project_paths(
            self.workflow, self.workflow, auto_create=False, project_root=self.root
        )
        backend = get_storage_backend(
            workflow_path=str(paths.io_dir.parent), workflow_name=self.workflow
        )
        backend.initialize()
        return backend

    def summaries(self) -> dict[str, list[str]]:
        """The summary each stored row of each stored file of the tool holds, by file."""
        backend = self._backend()
        try:
            return {
                path: sorted(
                    output["summary"]
                    for row in backend.read_target(ACTION, path)
                    if isinstance(output := row.get("content", {}).get(ACTION), dict)
                    and isinstance(output.get("summary"), str)
                )
                for path in sorted(backend.list_target_files(ACTION))
            }
        finally:
            backend.close()

    def dispositions(self) -> dict[str, tuple[str, str | None]]:
        """Each page's disposition at the tool, and its reason."""
        backend = self._backend()
        try:
            page_of = {
                record["source_guid"]: record["content"]["source"]["page_content"]
                for path in backend.list_source_files()
                for record in backend.read_source(path)
            }
            return {
                page_of[row["record_id"]]: (row["disposition"], row["reason"])
                for row in backend.get_disposition(ACTION)
                if row["record_id"] in page_of
            }
        finally:
            backend.close()


def _project(key: str, tmp_path: Path, monkeypatch) -> _Project:
    from agent_actions.utils import path_utils

    workflow, config, passes = WORKFLOWS[key]
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    home = root / "agent_workflow" / workflow
    (home / "agent_config" / f"{workflow}.yml").write_text(config)
    (root / "schema" / workflow / "roll_up_output.yml").write_text(ROLL_UP_SCHEMA)
    staging = home / "agent_io" / "staging"
    shutil.rmtree(staging)
    staging.mkdir()
    for name, pages in PAGES.items():
        (staging / name).write_text(json.dumps([{"page_content": page} for page in pages]))
    # Named for their tools, at one path for every workflow: discovery imports by module
    # name, and a second file registering the same tool would be refused as a duplicate.
    (root / "tools" / f"{ROLL_UP}.py").write_text(ROLL_UP_TOOL)
    (root / "tools" / f"{SHAPE}.py").write_text(SHAPE_TOOL)
    (root / "tag").write_text("v1")
    monkeypatch.chdir(root)
    monkeypatch.setenv("AGAC_BATCH_COMPLETE_AFTER_SECONDS", "0")
    monkeypatch.setenv("OLLAMA_API_KEY", "not-used")
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    # A run installs a global path manager; left behind, it sends later tests' writes here.
    monkeypatch.setattr(path_utils, "_global_path_manager", path_utils._global_path_manager)
    return _Project(root, workflow, passes)


@pytest.fixture(params=list(WORKFLOWS))
def project(request, tmp_path, monkeypatch):
    return _project(request.param, tmp_path, monkeypatch)


@pytest.fixture
def below_a_tool(tmp_path, monkeypatch):
    return _project("below_a_tool", tmp_path, monkeypatch)


def _broken_pages(dispositions: dict[str, tuple[str, str | None]]) -> dict[str, str]:
    return {page: disposition for page, (disposition, _) in dispositions.items()}


def test_the_file_it_raised_on_fails_its_records(project):
    project.breaks()

    project.run("--fresh")

    dispositions = project.dispositions()
    assert _broken_pages(dispositions) == {
        "Page alpha.": "failed",
        "Page beta.": "failed",
        "Page gamma.": "success",
        "Page delta.": "success",
    }, "nothing names the records of the file the tool raised on"
    assert "the roll-up of pages1 broke" in (dispositions["Page alpha."][1] or "")
    assert project.status() == "completed_with_failures"
    stored = project.summaries()
    assert stored.get(BROKEN_FILE, []) == []
    assert len(stored["pages2.json"]) == 2


def test_a_retry_runs_the_tool_on_that_file_again(project):
    project.breaks()
    project.run("--fresh")
    project.breaks(on=False)

    result = project.retry()

    assert result.exit_code == 0, result.output
    assert "Nothing to retry" not in result.output, result.output
    assert set(_broken_pages(project.dispositions()).values()) == {"success"}
    pages1 = project.summaries()[BROKEN_FILE]
    assert len(pages1) == 2 and all(summary.startswith("v1 ") for summary in pages1)
    assert project.status() == "completed"


def test_after_an_edit_the_file_keeps_no_row_from_before_it(project):
    """The edit resets the action above the tool and the tool with it."""
    project.run("--fresh")
    assert project.status() == "completed"
    assert all(len(rows) == 2 for rows in project.summaries().values())
    project.edit_upstream()
    project.tag("v2")
    project.breaks()

    project.run()

    stored = project.summaries()
    assert stored.get(BROKEN_FILE, []) == [], "a row from before the edit"
    assert len(stored["pages2.json"]) == 2
    assert all(summary.startswith("v2 ") for summary in stored["pages2.json"])
    assert project.dispositions()["Page alpha."][0] == "failed"
    assert project.status() == "completed_with_failures"


def test_a_retry_the_tool_raises_under_fails_the_record_it_repaired(below_a_tool):
    """Page alpha fails above the tool; the retry repairs it there, then the tool raises
    on its file. The repaired record is failed at the tool, so the next retry gets it."""
    project = below_a_tool
    project.breaks(flag=UPSTREAM_FLAG)
    project.run("--fresh")
    assert project.dispositions()["Page alpha."][0] == "unprocessed"
    project.breaks(on=False, flag=UPSTREAM_FLAG)
    project.breaks()

    result = project.retry()

    assert result.exit_code == 0, result.output
    disposition, reason = project.dispositions().get("Page alpha.", (None, None))
    assert disposition == "failed", "the record the retry repaired is named nowhere"
    assert "the roll-up of pages1 broke" in (reason or "")
    assert project.status() == "completed_with_failures"

    project.breaks(on=False)
    result = project.retry()

    assert result.exit_code == 0, result.output
    assert "Nothing to retry" not in result.output, result.output
    assert project.dispositions()["Page alpha."][0] == "success"
    assert "v1 v1 Page alpha." in project.summaries()[BROKEN_FILE]
    assert project.status() == "completed"
