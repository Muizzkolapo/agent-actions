"""A guard written `x BETWEEN a AND b` keeps the records inside the range (1365).

The clause parsed as `(x BETWEEN a) AND b`, false for every record: under
`on_false: filter` everything below the guard was skipped and the run exited 0, and under
`NOT (...)` every record passed.

`summarize`, then `publish` behind the guard, then `archive`; each of the two staged files
holds a page 1 and a page 2. Every command is a real `agac run` in its own process.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

FIXTURE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "between_range"
FILES = ("pages1.json", "pages2.json")
BELOW = ("publish", "archive")

_SCHEMA = """\
name: between_range_page
fields:
  - id: summary
    type: string
  - id: exam_density
    type: string
additionalProperties: true
"""

_PROMPTS = """\
{prompt Archive}
Archive this page.
## PAGE
{{ source.page_content }}
```json
{"summary": "...", "exam_density": "high|medium|low"}
```
{end_prompt}
"""


def _config(run_mode: str, condition: str) -> str:
    return f"""\
name: {WORKFLOW}
description: "A guard on a range"
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
  - name: summarize
    intent: "Summarise"
    schema: between_range_page
    prompt: $p.Summarize
    context_scope: {{ observe: [source.page_content] }}
  - name: publish
    dependencies: [summarize]
    intent: "Publish"
    schema: between_range_page
    prompt: $p.Publish
    context_scope: {{ observe: [summarize.summary, source.page_content] }}
    guard: {{ condition: {json.dumps(condition)}, on_false: filter }}
  - name: archive
    dependencies: [publish]
    intent: "Archive"
    schema: between_range_page
    prompt: ${WORKFLOW}.Archive
    context_scope: {{ observe: [publish.summary, source.page_content] }}
"""


class Project:
    def __init__(self, base: Path, run_mode: str, condition: str) -> None:
        self.root = base / "project"
        shutil.copytree(FIXTURE, self.root, ignore=shutil.ignore_patterns("logs"))
        workflow = self.root / "agent_workflow" / WORKFLOW
        (workflow / "agent_config").mkdir(parents=True)
        (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_config(run_mode, condition))
        staging = workflow / "agent_io" / "staging"
        staging.mkdir(parents=True)
        for name in FILES:
            (staging / name).write_text(
                json.dumps(
                    [
                        {"page_id": f"{name}-{page_no}", "page_no": page_no, "page_content": "A."}
                        for page_no in (1, 2)
                    ]
                )
            )
        (self.root / "schema" / WORKFLOW).mkdir()
        (self.root / "schema" / WORKFLOW / "between_range_page.yml").write_text(_SCHEMA)
        (self.root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
        (self.root / ".env").write_text("OLLAMA_API_KEY=not-used\n")

    def agac(self, *args: str):
        return run_agac(
            self.root,
            *args,
            env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0", "COLUMNS": "240"},
        )

    def run_to_the_end(self) -> None:
        """`agac run` until nothing is in flight: once online, a run per batch level."""
        args = ["run", "-a", WORKFLOW, "--fresh"]
        for _ in range(6):
            result = self.agac(*args)
            output = result.stdout + result.stderr
            assert result.returncode == 0, output
            if "run again" not in output:
                return
            args = ["run", "-a", WORKFLOW]
        pytest.fail(f"the workflow never stopped asking to be run again:\n{output}")

    def _query(self, sql: str, *params: str) -> list[tuple]:
        (db,) = (self.root / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()

    def _page_no(self) -> dict[str, int]:
        pages: dict[str, int] = {}
        for (blob,) in self._query("select data from source_data"):
            loaded = json.loads(blob)
            for row in loaded if isinstance(loaded, list) else [loaded]:
                pages[row["source_guid"]] = row["content"]["source"]["page_no"]
        return pages

    def pages(self, action: str, disposition: str) -> list[int]:
        """The page number of each record *action* holds under *disposition*."""
        page_no = self._page_no()
        return sorted(
            page_no[record]
            for record, held in self._query(
                "select record_id, disposition from record_disposition "
                "where action_name = ? and record_id != '__node__'",
                action,
            )
            if held == disposition
        )

    def statuses(self) -> dict[str, str]:
        path = self.root / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
        return {action: entry["status"] for action, entry in json.loads(path.read_text()).items()}


def _ran(tmp_path: Path, run_mode: str, condition: str) -> Project:
    project = Project(tmp_path, run_mode, condition)
    project.run_to_the_end()
    return project


MODES = ["online", "batch"]


@pytest.mark.parametrize("run_mode", MODES)
def test_the_guard_keeps_the_pages_inside_the_range(tmp_path, run_mode):
    project = _ran(tmp_path, run_mode, "source.page_no BETWEEN 2 AND 10")

    assert project.pages("publish", "filtered") == [1, 1]
    for action in BELOW:
        assert project.pages(action, "success") == [2, 2], action
    assert set(project.statuses().values()) == {"completed"}


@pytest.mark.parametrize("run_mode", MODES)
def test_under_not_the_guard_keeps_the_pages_outside_the_range(tmp_path, run_mode):
    project = _ran(tmp_path, run_mode, "NOT (source.page_no BETWEEN 2 AND 10)")

    assert project.pages("publish", "filtered") == [2, 2]
    for action in BELOW:
        assert project.pages(action, "success") == [1, 1], action


@pytest.mark.parametrize(
    "condition, kept",
    [
        ("source.page_no NOT BETWEEN 2 AND 10", [1, 1]),
        ("source.page_no BETWEEN 1 AND 1", [1, 1]),
        ("source.page_no BETWEEN 1 AND 10", [1, 1, 2, 2]),
        ("source.page_no BETWEEN 1 AND 10 AND source.page_no == 2", [2, 2]),
        ("source.page_no BETWEEN [2, 10]", [2, 2]),
    ],
)
def test_each_way_of_writing_the_range_keeps_what_it_names(tmp_path, condition, kept):
    project = _ran(tmp_path, "online", condition)

    for action in BELOW:
        assert project.pages(action, "success") == kept, action


@pytest.mark.parametrize(
    "condition",
    ["source.page_no BETWEEN 2", "source.page_no BETWEEN source.page_no AND 10"],
)
def test_a_range_the_guard_cannot_test_stops_the_run_before_it_starts(tmp_path, condition):
    """Either clause was accepted and false for every record."""
    project = Project(tmp_path, "online", condition)

    result = project.agac("run", "-a", WORKFLOW, "--fresh")

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "BETWEEN [a, b]" in output
    assert not list((project.root / "agent_workflow" / WORKFLOW / "agent_io").glob("store/*.db"))
