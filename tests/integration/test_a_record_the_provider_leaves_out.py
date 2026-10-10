"""A record the provider leaves out of a batch's results is that action's failure.

The provider answers a file's batch but leaves one record out. With no `retry:` block,
or with retry turned off, nothing sends that record again in the collect pass. It was
stored as a cascade casualty, `unprocessed` with reason `batch_not_returned`: the action
read `completed`, `agac retry` found nothing, and every later run skipped the action, so
only `agac run --fresh` brought the record back.

With retry on, a retry batch the provider refused left the record the same way.

Each run is its own `agac run` process against the agac provider mock, which answers
every task it was given; a record is lost the way a provider loses one, by taking its
task out of the submitted batch before the run that collects it. A refused retry batch
is a sitecustomize standing in for the provider, which refuses any batch sent to retry.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "map_reduce_fanin_check"
WORKFLOW = "map_reduce_fanin_check"
LOST = "gamma"
_ENV = {"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0", "OPENAI_API_KEY": "not-used"}

_RECAP = """

@udf_tool()
def recap(data: dict[str, Any]) -> dict[str, Any]:
    answer = data.get("summarize") or data.get("merge_direct") or {}
    return {"recap": f"recap of {answer}"}
"""

_HEAD = """\
name: map_reduce_fanin_check
description: "A batch action whose provider leaves one record out"
version: "1.0.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: stage_items
    kind: tool
    impl: stage_items
    intent: "Stage"
    schema: { item_id: string, text: string }
    context_scope: { observe: [source.item_id, source.text] }
"""

_BATCH = """\
    run_mode: batch
    model_vendor: agac-provider
    model_name: agac-model
    api_key: OPENAI_API_KEY
"""

_SUMMARIZE = (
    _HEAD
    + """\
  - name: summarize
    dependencies: [stage_items]
    intent: "Summarize"
    prompt: "Summarize the item."
    schema: { summary: string }
    context_scope: { observe: [stage_items.*] }
"""
    + _BATCH
    + "{retry}"
    + """\
  - name: recap
    kind: tool
    impl: recap
    dependencies: [summarize]
    intent: "Recap"
    schema: { recap: string }
    context_scope: { observe: [summarize.*] }
"""
)

_MERGE = (
    _HEAD
    + """\
  - name: vote_direct
    kind: tool
    impl: cast_vote_direct
    dependencies: [stage_items]
    intent: "Vote"
    versions: { param: voter_id, range: [1, 2] }
    schema: { vote: string, voted_item: string }
    context_scope: { observe: [stage_items.*] }
  - name: merge_direct
    dependencies: [vote_direct]
    intent: "Merge the votes"
    prompt: "Merge the votes."
    version_consumption: { source: vote_direct, pattern: merge }
    schema: { decision: string }
    context_scope: { observe: [vote_direct.*] }
"""
    + _BATCH
    + "{retry}"
    + """\
  - name: recap
    kind: tool
    impl: recap
    dependencies: [merge_direct]
    intent: "Recap"
    schema: { recap: string }
    context_scope: { observe: [merge_direct.*] }
"""
)

_RETRY_ON = "    retry: { enabled: true, max_attempts: 3 }\n"

# (workflow, batch action, its retry: block, the retry batch the provider refuses or 0)
SCENARIOS = {
    "no-retry-block": (_SUMMARIZE, "summarize", "", 0),
    "retry-enabled-false": (_SUMMARIZE, "summarize", "    retry: { enabled: false }\n", 0),
    "retry-false": (_SUMMARIZE, "summarize", "    retry: false\n", 0),
    "version-merge": (_MERGE, "merge_direct", "", 0),
    "first-retry-refused": (_SUMMARIZE, "summarize", _RETRY_ON, 1),
    "second-retry-refused": (_SUMMARIZE, "summarize", _RETRY_ON, 2),
}

_REFUSE_RETRY = """\
import os

if os.environ.get("REFUSE_RETRY_BATCH"):
    from agent_actions.llm.providers.agac import batch_client as _client

    _submit = _client.AgacBatchClient._submit_to_provider_api

    def _refuse_retry(self, input_file, batch_name):
        if batch_name.endswith("_retry"):
            raise ConnectionError("the provider refused the batch")
        return _submit(self, input_file, batch_name)

    _client.AgacBatchClient._submit_to_provider_api = _refuse_retry
"""


def _project(root: Path, config: str) -> Path:
    shutil.copytree(EXAMPLE, root)
    (root / "schema").mkdir(exist_ok=True)
    tools = root / "tools" / WORKFLOW / "pipeline_tools.py"
    tools.write_text(tools.read_text() + _RECAP)
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(config)
    (root / ".env").write_text("OPENAI_API_KEY=not-used\n")
    (root.parent / "site").mkdir()
    (root.parent / "site" / "sitecustomize.py").write_text(_REFUSE_RETRY)
    return root


def _run(project: Path, *args: str, refuse_retry: bool = False) -> SimpleNamespace:
    env = dict(_ENV)
    if refuse_retry:
        env.update(PYTHONPATH=str(project.parent / "site"), REFUSE_RETRY_BATCH="1")
    result = run_agac(project, "run", "-a", WORKFLOW, *args, env=env)
    return SimpleNamespace(code=result.returncode, output=result.stdout + result.stderr)


def _retry(project: Path) -> SimpleNamespace:
    result = run_agac(project, "retry", "-a", WORKFLOW, env=_ENV)
    return SimpleNamespace(code=result.returncode, output=result.stdout + result.stderr)


def _statuses(project: Path) -> dict[str, str]:
    path = project / "agent_workflow" / WORKFLOW / "agent_io" / ".agent_status.json"
    return {name: entry["status"] for name, entry in json.loads(path.read_text()).items()}


def _batches(project: Path) -> dict[Path, list[dict]]:
    held = project / ".agac" / "batch_state"
    return {path: json.loads(path.read_text())["tasks"] for path in held.glob("*.json")}


def _lose(batch: Path) -> str:
    """Take the lost record's task out of a submitted batch, and hand back its custom_id."""
    held = json.loads(batch.read_text())
    (lost,) = [task for task in held["tasks"] if LOST in json.dumps(task)]
    held["tasks"].remove(lost)
    batch.write_text(json.dumps(held))
    return lost["custom_id"]


def _store(project: Path) -> sqlite3.Connection:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def _rows(project: Path, action: str) -> list[dict]:
    con = _store(project)
    try:
        blobs = [
            row[0]
            for row in con.execute("select data from target_data where action_name = ?", (action,))
        ]
    finally:
        con.close()
    rows: list[dict] = []
    for blob in blobs:
        loaded = json.loads(blob)
        rows.extend(loaded if isinstance(loaded, list) else [loaded])
    return rows


def _lost_guid(project: Path) -> str:
    (guid,) = [
        row["source_guid"]
        for row in _rows(project, "stage_items")
        if row["content"]["stage_items"]["item_id"] == LOST
    ]
    return guid


def _dispositions(project: Path, action: str) -> dict[str, tuple[str, str]]:
    con = _store(project)
    try:
        return {
            record_id: (disposition, reason or "")
            for record_id, disposition, reason in con.execute(
                "select record_id, disposition, reason from record_disposition "
                "where action_name = ? and record_id != '__node__'",
                (action,),
            )
        }
    finally:
        con.close()


def _answer(project: Path, action: str, guid: str) -> object:
    (row,) = [row for row in _rows(project, action) if row["source_guid"] == guid]
    return row["content"].get(action)


@pytest.fixture(scope="class", params=sorted(SCENARIOS))
def runs(request, tmp_path_factory):
    template, action, retry, refused = SCENARIOS[request.param]
    project = _project(
        tmp_path_factory.mktemp(request.param) / "project", template.replace("{retry}", retry)
    )
    submitted = _run(project, "--fresh")
    assert submitted.code == 0, submitted.output
    (batch,) = _batches(project)
    custom_id = _lose(batch)
    if refused == 2:
        resent = _run(project)
        (retry_batch,) = set(_batches(project)) - {batch}
        assert _lose(retry_batch) == custom_id, resent.output

    before_collect = set(_batches(project))
    collected = _run(project, refuse_retry=bool(refused))
    sent_by_collect = set(_batches(project)) - before_collect
    guid = _lost_guid(project)
    after_collect = SimpleNamespace(
        statuses=_statuses(project),
        dispositions=_dispositions(project, action),
        readers=_dispositions(project, "recap"),
        answer=_answer(project, action, guid),
    )

    before_retry = set(_batches(project))
    retried = _retry(project)
    sent_by_retry = [
        [task["custom_id"] for task in tasks]
        for path, tasks in _batches(project).items()
        if path not in before_retry
    ]
    finished = [_run(project)]
    while "run again" in finished[-1].output and len(finished) < 4:
        finished.append(_run(project))
    return SimpleNamespace(
        project=project,
        action=action,
        custom_id=custom_id,
        guid=guid,
        collected=collected,
        sent_by_collect=sent_by_collect,
        after_collect=after_collect,
        retried=retried,
        sent_by_retry=sent_by_retry,
        finished=finished,
    )


class TestARecordTheProviderLeavesOut:
    def test_the_collect_pass_sends_nothing_again(self, runs):
        assert runs.collected.code == 0, runs.collected.output
        assert runs.sent_by_collect == set(), runs.collected.output

    def test_the_record_is_the_actions_failure(self, runs):
        assert runs.after_collect.dispositions[runs.guid] == ("failed", "batch_not_returned")
        others = [
            disposition
            for guid, disposition in runs.after_collect.dispositions.items()
            if guid != runs.guid
        ]
        assert others == [("success", "")] * 2, runs.after_collect.dispositions

    def test_the_action_completes_with_failures(self, runs):
        assert runs.after_collect.statuses[runs.action] == "completed_with_failures", (
            runs.collected.output
        )

    def test_its_readers_skip_it(self, runs):
        disposition, _ = runs.after_collect.readers[runs.guid]
        assert disposition != "success", runs.after_collect.readers
        assert runs.after_collect.answer is None

    def test_agac_retry_sends_it_again(self, runs):
        assert runs.retried.code == 0, runs.retried.output
        assert "Nothing to retry" not in runs.retried.output, runs.retried.output
        assert runs.sent_by_retry == [[runs.custom_id]], runs.retried.output

    def test_the_retry_stores_its_answer_and_its_readers_answer_it(self, runs):
        last = runs.finished[-1]
        assert last.code == 0, last.output
        assert _statuses(runs.project)[runs.action] == "completed", last.output
        assert _dispositions(runs.project, runs.action)[runs.guid] == ("success", "")
        assert _answer(runs.project, runs.action, runs.guid), last.output
        assert _dispositions(runs.project, "recap")[runs.guid] == ("success", "")
        assert _answer(runs.project, "recap", runs.guid), last.output
