"""A record tool's output that fails its schema fails that record, not its file (1333).

A `kind: tool` action checks each record's output against its schema. One record's
output failing it left the record loop and was caught for the whole file: every record
of that file was lost, the valid ones with it, no disposition named any of them, and the
action read `completed` with exit 0. `agac retry` found nothing to retry, the next run
found the action complete, and after an edit the file kept its rows from before it.

Every run is an `agac run` or `agac retry` through the CLI, executor, store and mock
provider. Only the fault is stood in for: while a flag file exists, the tool answers
page alpha with a number where its schema asks for a string.
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
BAD_PAGE = "Page alpha."
FLAG = "alpha_breaks"
SCHEMA = Path("schema") / "tool_action" / "tool_action_output.yml"

# Answers each page with its text, tagged with what the `tag` file says; while the flag
# file exists, page alpha's summary is a number, which the schema refuses.
IMPL = "shape_page_or_break"
TOOL = f"""from pathlib import Path
from typing import Any

from agent_actions import udf_tool


@udf_tool
def {IMPL}(data: Any, *args) -> list[dict]:
    page = data["source"]["page_content"]
    if page == {BAD_PAGE!r} and Path({FLAG!r}).exists():
        return [{{"summary": 42, "exam_density": "low"}}]
    return [{{"summary": Path("tag").read_text() + " " + page, "exam_density": "low"}}]
"""

FIRST_STAGE = """name: tool_action
description: "A record tool over staged pages"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: flatten
    kind: tool
    intent: "Flatten"
    schema: tool_action_output
    impl: shape_page_or_break
    context_scope: { observe: [source.page_content] }
    expect: { repair: none }
"""

BELOW_AN_LLM = """name: batch_field_rules
description: "A record tool reading an LLM action"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: RUN_MODE
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: summarize
    intent: "Summarise"
    schema: batch_field_rules_output
    prompt: $p.Summarize
    context_scope: { observe: [source.page_content] }
    expect: { repair: none }
  - name: tally
    kind: tool
    dependencies: [summarize]
    run_mode: online
    intent: "Tally"
    schema: tool_action_output
    impl: shape_page_or_break
    context_scope: { observe: [summarize.summary, source.page_content] }
    expect: { repair: none }
"""

# (workflow, the record tool, its config, runs that finish a first pass)
WORKFLOWS = {
    "first_stage": ("tool_action", "flatten", FIRST_STAGE, 1),
    "below_online": ("batch_field_rules", "tally", BELOW_AN_LLM.replace("RUN_MODE", "online"), 1),
    # The first run submits the batch above the tool; the second collects it.
    "below_batch": ("batch_field_rules", "tally", BELOW_AN_LLM.replace("RUN_MODE", "batch"), 2),
}


class _Project:
    def __init__(self, root: Path, workflow: str, action: str, passes: int) -> None:
        self.root = root
        self.workflow = workflow
        self.action = action
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

    def breaks(self, on: bool = True) -> None:
        if on:
            (self.root / FLAG).touch()
        else:
            (self.root / FLAG).unlink()

    def tag(self, tag: str) -> None:
        (self.root / "tag").write_text(tag)

    def status(self) -> str:
        io = self.root / "agent_workflow" / self.workflow / "agent_io"
        return json.loads((io / ".agent_status.json").read_text())[self.action]["status"]

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
        """The summary each stored row of each stored file holds, by file."""
        backend = self._backend()
        try:
            return {
                path: sorted(
                    output["summary"]
                    for row in backend.read_target(self.action, path)
                    if isinstance(output := row.get("content", {}).get(self.action), dict)
                    and isinstance(output.get("summary"), str)
                )
                for path in sorted(backend.list_target_files(self.action))
            }
        finally:
            backend.close()

    def dispositions(self) -> dict[str, tuple[str, str | None]]:
        """Each page's disposition at the record tool, and its reason."""
        backend = self._backend()
        try:
            page_of = {
                record["source_guid"]: record["content"]["source"]["page_content"]
                for path in backend.list_source_files()
                for record in backend.read_source(path)
            }
            return {
                page_of[row["record_id"]]: (row["disposition"], row["reason"])
                for row in backend.get_disposition(self.action)
                if row["record_id"] in page_of
            }
        finally:
            backend.close()


@pytest.fixture(params=list(WORKFLOWS))
def project(request, tmp_path, monkeypatch):
    from agent_actions.utils import path_utils

    workflow, action, config, passes = WORKFLOWS[request.param]
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    home = root / "agent_workflow" / workflow
    (home / "agent_config" / f"{workflow}.yml").write_text(config)
    staging = home / "agent_io" / "staging"
    shutil.rmtree(staging)
    staging.mkdir()
    for name, pages in PAGES.items():
        (staging / name).write_text(json.dumps([{"page_content": page} for page in pages]))
    # Named for its tool, at one path for every workflow: discovery imports by module
    # name, and a second file registering the same tool would be refused as a duplicate.
    (root / "tools" / f"{IMPL}.py").write_text(TOOL)
    (root / "tag").write_text("v1")
    monkeypatch.chdir(root)
    monkeypatch.setenv("AGAC_BATCH_COMPLETE_AFTER_SECONDS", "0")
    monkeypatch.setenv("OLLAMA_API_KEY", "not-used")
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    # A run installs a global path manager; left behind, it sends later tests' writes here.
    monkeypatch.setattr(path_utils, "_global_path_manager", path_utils._global_path_manager)
    return _Project(root, workflow, action, passes)


def test_the_file_keeps_its_valid_records_and_the_bad_one_fails(project):
    project.breaks()

    project.run("--fresh")

    assert project.summaries() == {
        "pages1.json": ["v1 Page beta."],
        "pages2.json": ["v1 Page delta.", "v1 Page gamma."],
    }, "a valid record was lost with its file"
    dispositions = project.dispositions()
    disposition, reason = dispositions.pop(BAD_PAGE)
    assert disposition == "failed"
    assert "42 is not of type 'string'" in (reason or "")
    assert set(dispositions.values()) == {("success", None)}
    assert project.status() == "completed_with_failures"


def test_a_retry_answers_the_bad_record_again(project):
    project.breaks()
    project.run("--fresh")
    project.breaks(on=False)

    result = project.retry()

    assert result.exit_code == 0, result.output
    assert "Nothing to retry" not in result.output, result.output
    assert project.dispositions()[BAD_PAGE] == ("success", None)
    assert project.summaries()["pages1.json"] == ["v1 Page alpha.", "v1 Page beta."]
    assert project.status() == "completed"


def test_after_an_edit_the_file_keeps_no_row_from_before_it(project):
    """The schema edit resets the tool, and its answers change with the tag."""
    project.run("--fresh")
    assert project.status() == "completed"
    schema = project.root / SCHEMA
    field = "  - id: exam_density\n"
    described = field + "    description: How densely the page carries exam material\n"
    assert field in schema.read_text()
    schema.write_text(schema.read_text().replace(field, described))
    project.tag("v2")
    project.breaks()

    project.run()

    assert project.summaries() == {
        "pages1.json": ["v2 Page beta."],
        "pages2.json": ["v2 Page delta.", "v2 Page gamma."],
    }, "a row from before the edit"
    assert project.dispositions()[BAD_PAGE][0] == "failed"
    assert project.status() == "completed_with_failures"
