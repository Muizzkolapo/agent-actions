"""A guard written `NOT x == 1`, unparenthesised, keeps the records it names (1382).

The clause parsed as `(NOT x) == 1`: `NOT x` is a boolean, so the comparison was
decided by `x`'s truthiness rather than its value, false for every record whose
field was truthy. Only `NOT (x == 1)` negated the comparison.

`summarize`, then `publish` behind the guard, then `archive`; each of the two
staged files holds a page 1 and a page 2. Every command is a real `agac run` in
its own process.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.store import stored_rows

FIXTURE = Path(__file__).parent / "fixtures" / "expectation_authors"
WORKFLOW = "not_precedence"
FILES = ("pages1.json", "pages2.json")
BELOW = ("publish", "archive")

_SCHEMA = """\
name: not_precedence_page
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


def _config(run_mode: str, condition: str) -> str:
    return f"""\
name: {WORKFLOW}
description: "A guard under NOT"
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
    schema: not_precedence_page
    prompt: $p.Summarize
    context_scope: {{ observe: [source.page_content] }}
  - name: publish
    dependencies: [summarize]
    intent: "Publish"
    schema: not_precedence_page
    prompt: $p.Publish
    context_scope: {{ observe: [summarize.summary, source.page_content] }}
    guard: {{ condition: {json.dumps(condition)}, on_false: filter }}
  - name: archive
    dependencies: [publish]
    intent: "Archive"
    schema: not_precedence_page
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
        (self.root / "schema" / WORKFLOW / "not_precedence_page.yml").write_text(_SCHEMA)
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
        return stored_rows(db, sql, *params)

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


def _ran(tmp_path: Path, run_mode: str, condition: str) -> Project:
    project = Project(tmp_path, run_mode, condition)
    project.run_to_the_end()
    return project


@pytest.mark.parametrize(
    ("run_mode", "condition"),
    [
        # Should keep page 2, not decide by page_no's truthiness.
        ("online", "NOT source.page_no == 1"),
        ("batch", "NOT source.page_no == 1"),
        # The parenthesised form already worked and still does.
        ("online", "NOT (source.page_no == 1)"),
    ],
    ids=["bare-online", "bare-batch", "parenthesised"],
)
def test_the_guard_keeps_the_record_not_named_by_the_comparison(tmp_path, run_mode, condition):
    project = _ran(tmp_path, run_mode, condition)

    assert project.pages("publish", "filtered") == [1, 1]
    for action in BELOW:
        assert project.pages(action, "success") == [2, 2], action
