"""A guard comparing a field to a string containing and/or/not/in/etc. runs (1383).

The old field-name pre-check split the raw clause on those words with no regard for
quotes, refusing `source.title == "rock and roll"` though the clause is valid.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.store import stored_rows

FIXTURE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "guard_reserved_word"
BELOW = ("publish", "archive")

_SCHEMA = """\
name: guard_reserved_word_page
fields:
  - id: summary
    type: string
additionalProperties: true
"""

_PROMPTS = """\
{prompt Archive}
Archive this page.
## PAGE
{{ source.page_content }}
```json
{"summary": "..."}
```
{end_prompt}
"""


def _config(condition: str) -> str:
    return f"""\
name: {WORKFLOW}
description: "A guard on a string containing a reserved word"
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
  - name: summarize
    intent: "Summarise"
    schema: guard_reserved_word_page
    prompt: $p.Summarize
    context_scope: {{ observe: [source.page_content, source.title] }}
  - name: publish
    dependencies: [summarize]
    intent: "Publish"
    schema: guard_reserved_word_page
    prompt: $p.Publish
    context_scope: {{ observe: [summarize.summary, source.page_content] }}
    guard: {{ condition: {json.dumps(condition)}, on_false: filter }}
  - name: archive
    dependencies: [publish]
    intent: "Archive"
    schema: guard_reserved_word_page
    prompt: ${WORKFLOW}.Archive
    context_scope: {{ observe: [publish.summary, source.page_content] }}
"""


class Project:
    def __init__(self, base: Path, condition: str) -> None:
        self.root = base / "project"
        shutil.copytree(FIXTURE, self.root, ignore=shutil.ignore_patterns("logs"))
        workflow = self.root / "agent_workflow" / WORKFLOW
        (workflow / "agent_config").mkdir(parents=True)
        (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_config(condition))
        staging = workflow / "agent_io" / "staging"
        staging.mkdir(parents=True)
        pages = [
            {"page_id": "p1", "title": "rock and roll", "page_content": "A."},
            {"page_id": "p2", "title": "jazz", "page_content": "B."},
        ]
        (staging / "pages.json").write_text(json.dumps(pages))
        (self.root / "schema" / WORKFLOW).mkdir()
        (self.root / "schema" / WORKFLOW / "guard_reserved_word_page.yml").write_text(_SCHEMA)
        (self.root / "prompt_store" / f"{WORKFLOW}.md").write_text(_PROMPTS)
        (self.root / ".env").write_text("OLLAMA_API_KEY=not-used\n")

    def agac(self, *args: str):
        return run_agac(
            self.root,
            *args,
            env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0", "COLUMNS": "240"},
        )

    def run_to_the_end(self) -> None:
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
        return stored_rows(db, sql, *params)

    def _title(self) -> dict[str, str]:
        titles: dict[str, str] = {}
        for (blob,) in self._query("select data from source_data"):
            loaded = json.loads(blob)
            for row in loaded if isinstance(loaded, list) else [loaded]:
                titles[row["source_guid"]] = row["content"]["source"]["title"]
        return titles

    def titles_held(self, action: str, disposition: str) -> list[str]:
        titles = self._title()
        return sorted(
            titles[record]
            for record, held in self._query(
                "select record_id, disposition from record_disposition "
                "where action_name = ? and record_id != '__node__'",
                action,
            )
            if held == disposition
        )


def test_the_guard_runs_on_a_string_containing_and(tmp_path):
    project = Project(tmp_path, 'source.title == "rock and roll"')
    project.run_to_the_end()

    assert project.titles_held("publish", "filtered") == ["jazz"]
    for action in BELOW:
        assert project.titles_held(action, "success") == ["rock and roll"], action


def test_the_guard_runs_on_a_negated_string_comparison_with_or_in_it(tmp_path):
    project = Project(tmp_path, 'source.title != "this or that"')
    project.run_to_the_end()

    for action in BELOW:
        assert sorted(project.titles_held(action, "success")) == ["jazz", "rock and roll"], action
