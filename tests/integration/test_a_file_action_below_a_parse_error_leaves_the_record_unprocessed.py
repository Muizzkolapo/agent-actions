"""A FILE action below a record an LLM action failed to parse leaves it unprocessed (1907).

When `extract` fails one record with a parse error (here a refusal), its tombstone holds
`extract` as `{raw_response, _parse_error, ...}`, without the fields an action below
observes. The FILE tool or HITL action below ran its `context_scope` pass over every input
record before the cascade filter, refused that tombstone as `observe_field_missing` and
stored `failed` for it at the FILE action. `agac retry --filter extract:<id>` then removed
only `unprocessed` rows below, so the wrong `failed` row stayed with no input left to
repair it, and every `agac retry` exited 3.

Now the record is `unprocessed / upstream_unprocessed` at the FILE action, as at a RECORD
action, `--filter` leaves nothing for it below `extract`, and the retry after it exits 0.
A store an older run left with the `failed` row is cleared by `--filter` too. Each command
is its own `agac` process with the sandbox mock following a scenario.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_actions.cli.exit_codes import EXIT_RECORD_FAILURES, EXIT_SUCCESS
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from tests._support.agac_cli import run_agac
from tests.helpers.store import stored_rows

WORKFLOW = "parse_cascade"
ENV = {"OPENAI_API_KEY": ""}
ROWS = [{"page_id": f"p{n}", "text": text} for n, text in enumerate(["calm", "wind", "tide"])]
UNPROCESSED = ("unprocessed", "upstream_unprocessed")

REFUSE_P1 = """records:
  - match: {source.page_id: p1}
    actions: {extract: {error: refusal}}
"""

FILE_TOOL = """\
    kind: tool
    granularity: File
    impl: tally_pages
    schema: tally_output
"""
HITL = """\
    kind: hitl
    hitl: { port: 3998, instructions: "Review the codes", timeout: 5 }
"""

CONFIG = """\
name: parse_cascade
description: "An LLM action that refuses a record, and a FILE action that reads its field"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: openai
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
  retry: { max_attempts: 1, base_delay: 0.01, max_delay: 0.01 }
actions:
  - name: extract
    intent: "Extract"
    schema: extract_output
    prompt: $parse_cascade.Extract
    context_scope: { observe: [source.page_id, source.text] }
  - name: review
    dependencies: [extract]
    intent: "Review"
%(review)s    context_scope: { observe: [extract.code, source.page_id] }
"""

PROMPTS = """# parse_cascade - prompt store

{prompt Extract}
Extract a code for this text.
{{ source.text }}
{end_prompt}
"""

SCHEMAS = {
    "extract_output": (
        "name: extract_output\nfields:\n  - id: page_id\n    type: string\n"
        "  - id: code\n    type: string\n"
    ),
    "tally_output": (
        "name: tally_output\nfields:\n  - id: code\n    type: string\nadditionalProperties: true\n"
    ),
}

TOOLS = """from typing import Any

from agent_actions import udf_tool
from agent_actions.utils.udf_management.registry import Granularity


@udf_tool(granularity=Granularity.FILE)
def tally_pages(data: Any, *args):
    for record in data:
        record["code"] = "tallied " + str(record.get("code"))
    return data
"""


def _project(base: Path, review: str = FILE_TOOL) -> Path:
    root = base / "project"
    workflow_dir = root / "agent_workflow" / WORKFLOW
    (workflow_dir / "agent_config").mkdir(parents=True)
    (workflow_dir / "agent_io" / "staging").mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "prompt_store").mkdir()
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "agent_actions.yml").write_text(
        "default_agent_config: {model_name: gpt-4o-mini}\nschema_path: schema\n"
        "tool_path: [tools]\n"
    )
    (workflow_dir / "agent_config" / f"{WORKFLOW}.yml").write_text(CONFIG % {"review": review})
    (workflow_dir / "agent_io" / "staging" / "pages.json").write_text(json.dumps(ROWS))
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(PROMPTS)
    for name, text in SCHEMAS.items():
        (root / "schema" / WORKFLOW / f"{name}.yml").write_text(text)
    (root / "tools" / WORKFLOW / "tally_tools.py").write_text(TOOLS)
    (root / "fail.yml").write_text(REFUSE_P1)
    return root


def _agac(root: Path, command: str, *args: str, code: int) -> str:
    result = run_agac(root, command, "-w", WORKFLOW, "--sandbox", *args, env=ENV)
    said = result.stdout + result.stderr
    assert result.returncode == code, said
    return said


def _db(root: Path) -> Path:
    return root / "agent_workflow" / WORKFLOW / "agent_io" / "store" / f"{WORKFLOW}.sandbox.db"


def _dispositions(root: Path, action: str) -> dict[str, tuple[str, str | None]]:
    return {
        record: (disposition, reason)
        for record, disposition, reason in stored_rows(
            _db(root),
            "select record_id, disposition, reason from record_disposition "
            "where action_name = ? and record_id != '__node__'",
            action,
        )
    }


def _guids(root: Path, action: str) -> set[str]:
    guids: set[str] = set()
    for (blob,) in stored_rows(
        _db(root), "select data from target_data where action_name = ?", action
    ):
        loaded = json.loads(blob)
        guids |= {row["source_guid"] for row in (loaded if isinstance(loaded, list) else [])}
    return guids


def _refused(root: Path) -> str:
    (record_id,) = [
        record
        for record, (disposition, _) in _dispositions(root, "extract").items()
        if disposition == "failed"
    ]
    return record_id


def _status(root: Path, action: str) -> str:
    path = root / "agent_workflow" / WORKFLOW / "agent_io" / "sandbox" / ".agent_status.json"
    return json.loads(path.read_text())[action]["status"]


def _refusing_run(base: Path, review: str = FILE_TOOL) -> tuple[Path, str]:
    root = _project(base, review)
    _agac(root, "run", "--scenario", "fail.yml", code=EXIT_RECORD_FAILURES)
    return root, _refused(root)


def _filter(root: Path, record_id: str) -> str:
    return _agac(root, "retry", "--filter", f"extract:{record_id}", "--reason", "refused", code=0)


@pytest.mark.parametrize("review", [FILE_TOOL, HITL], ids=["file-tool", "hitl"])
class TestTheRecordIsUnprocessedAtTheFileAction:
    def test_after_the_run(self, tmp_path, review):
        root, refused = _refusing_run(tmp_path, review)

        assert _dispositions(root, "review")[refused] == UNPROCESSED
        assert _status(root, "review") == "completed"

    def test_a_filter_leaves_nothing_for_it_below_and_the_retry_exits_0(self, tmp_path, review):
        root, refused = _refusing_run(tmp_path, review)

        _filter(root, refused)

        assert refused not in _dispositions(root, "review")
        assert refused not in _guids(root, "review")
        _agac(root, "retry", "--scenario", "fail.yml", "--all", code=EXIT_SUCCESS)


def _as_an_older_run_left_it(root: Path, record_id: str, disposition: str = "failed") -> None:
    """The FILE action refused the record's tombstone as its own failure, as before."""
    backend = SQLiteBackend(str(_db(root)), WORKFLOW)
    backend.initialize()
    try:
        backend.clear_disposition("review", record_id=record_id)
        backend.set_dispositions_batch(
            [
                (
                    "review",
                    record_id,
                    disposition,
                    "context_scope.observe field 'extract.code' not found in this record",
                    "pages.json",
                    None,
                    None,
                )
            ]
        )
    finally:
        backend.close()
    path = root / "agent_workflow" / WORKFLOW / "agent_io" / "sandbox" / ".agent_status.json"
    statuses = json.loads(path.read_text())
    statuses["review"]["status"] = "completed_with_failures"
    path.write_text(json.dumps(statuses))


class TestAFilterClearsTheFailureAnOlderRunLeft:
    @pytest.mark.parametrize("disposition", ["failed", "exhausted"])
    def test_the_failure_row_goes_with_the_tombstone_and_the_retry_exits_0(
        self, tmp_path, disposition
    ):
        root, refused = _refusing_run(tmp_path)
        _as_an_older_run_left_it(root, refused, disposition)
        assert _dispositions(root, "review")[refused][0] == disposition
        assert refused in _guids(root, "review"), "the tombstone the filter removes"

        _filter(root, refused)

        assert refused not in _dispositions(root, "review")
        assert refused not in _guids(root, "review")
        assert _status(root, "review") == "completed"
        _agac(root, "retry", "--scenario", "fail.yml", "--all", code=EXIT_SUCCESS)

    def test_a_failure_at_a_reader_holding_no_tombstone_for_the_record_stays(self, tmp_path):
        """The control: without a stored row for the record there, its failure stays."""
        root, refused = _refusing_run(tmp_path)
        _as_an_older_run_left_it(root, refused)
        backend = SQLiteBackend(str(_db(root)), WORKFLOW)
        backend.initialize()
        try:
            for relative_path in backend.list_target_files("review"):
                rows = backend.read_target_for_rewrite("review", relative_path)
                kept = [row for row in rows if row.get("source_guid") != refused]
                backend.write_target("review", relative_path, kept)
        finally:
            backend.close()

        _filter(root, refused)

        assert _dispositions(root, "review")[refused][0] == "failed"
        assert _status(root, "review") == "completed_with_failures"

    def test_another_records_failure_stays_and_keeps_the_status(self, tmp_path):
        """The control: only the filtered record's failure is cleared below."""
        root, refused = _refusing_run(tmp_path)
        _as_an_older_run_left_it(root, refused)
        other = next(guid for guid in _guids(root, "review") if guid != refused)
        backend = SQLiteBackend(str(_db(root)), WORKFLOW)
        backend.initialize()
        try:
            backend.set_dispositions_batch(
                [("review", other, "failed", "its own failure", "pages.json", None, None)]
            )
        finally:
            backend.close()

        _filter(root, refused)

        assert refused not in _dispositions(root, "review")
        assert _dispositions(root, "review")[other] == ("failed", "its own failure")
        assert _status(root, "review") == "completed_with_failures"
