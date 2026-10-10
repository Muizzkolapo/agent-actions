"""An online action looks up the rows it stored under the name it stored them under.

The write names a file by its path below the input root: ``sub/page.json`` for a file
in a subdirectory, and ``page.json`` for a staged ``page.csv``. Carry-forward, the
carry of a repair and the per-record checkpoint each worked the name out again from
the input path and the file's own folder, and got ``page.json`` and ``page.csv``. A
lookup that misses finds no stored row, so a re-run sends done records to the model
again and a repair rewrites the file with only the records it named.

Driven from ``ProcessingPipeline.process`` and ``process_initial_stage`` against a real
store, with the strategy swapped or, where the checkpoint matters, only
``process_record``; and through ``agac retry`` for what a user sees.
"""

from __future__ import annotations

import csv
import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from agent_actions.config.types import RunMode
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    InitialStageContext,
    process_initial_stage,
)
from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
from agent_actions.processing.types import ProcessingResult
from agent_actions.record.envelope import RecordEnvelope
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from tests.integration.test_batch_rerun_matches_online import (
    ACTION,
    Answerer,
    _config,
    _Online,
    answers,
    rec,
)
from tests.integration.test_retry_ignores_record_cap import (
    RECORDS,
    SECOND_ACTION,
    SOURCE,
    TAG_TOOL,
    WORKFLOW,
    _fail,
    _record_ids,
    _stored_records,
)

DOWNSTREAM_FILES = ["page.json", "sub/page.json", "a/b/page.json"]
STAGED_FILES = ["page.json", "sub/page.json", "page.csv"]


def _held(backend: SQLiteBackend) -> dict[str, list[str]]:
    """Every file the action holds, by the name it is stored under."""
    backend._reconstruction_cache.clear()
    return {
        path: answers(backend.read_target_for_rewrite(ACTION, path))
        for path in backend.list_target_files(ACTION)
    }


def _answering(run: int, sent: list[str], stop_at: str | None = None):
    """The model, below the real strategy: its loop and checkpoint still run."""

    def process_record(self, item, context, *, skip_guard=False):
        guid = item["source_guid"]
        name = (item.get("content") or {}).get("source", {}).get("item") or guid
        if name == stop_at:
            raise KeyboardInterrupt
        sent.append(name)
        row = RecordEnvelope.build(ACTION, {"answer": f"{name}:0@run{run}"}, item)
        row["source_guid"] = guid
        return ProcessingResult.success(data=[row], source_guid=guid)

    return patch.object(OnlineLLMStrategy, "process_record", process_record)


@pytest.mark.parametrize("file", DOWNSTREAM_FILES)
def test_a_re_run_sends_only_the_input_it_has_not_answered(tmp_path, file):
    online = _Online(tmp_path, file)
    online.run(1, [rec("a1"), rec("a2")])

    held = online.run(2, [rec("a1"), rec("a2"), rec("a3")])

    assert online.sent == [["a1", "a2"], ["a3"]]
    assert held == ["processed:a1:0@run1", "processed:a2:0@run1", "processed:a3:0@run2"]


@pytest.mark.parametrize("file", DOWNSTREAM_FILES)
def test_a_repair_keeps_the_rows_of_the_records_it_did_not_name(tmp_path, file):
    """The file is rewritten whole, so a row the repair cannot find to carry is deleted,
    while its record's disposition still says it was answered."""
    online = _Online(tmp_path, file)
    inputs = [rec("a1"), rec("a2"), rec("a3")]
    online.run(1, inputs, Answerer({("a2", 1): "fail"}))

    held = online.run(2, inputs, retry=["a2"])

    assert held == ["processed:a1:0@run1", "processed:a2:0@run2", "processed:a3:0@run1"]


@pytest.mark.parametrize("file", DOWNSTREAM_FILES)
def test_a_resumed_run_takes_what_it_checkpointed_before_it_stopped(tmp_path, file):
    """The checkpoint is the stored row of a file the interrupted run never wrote, so it
    has to sit under the name the resumed run looks the file up by."""
    online = _Online(tmp_path, file)
    inputs = [rec("a1"), rec("a2"), rec("a3")]
    online._upstream_wrote(inputs)
    first: list[str] = []
    _config_, pipeline = online._pipeline({}, ())
    with _answering(1, first, stop_at="a2"), pytest.raises(KeyboardInterrupt):
        online._process(pipeline, inputs)

    again: list[str] = []
    _config_, pipeline = online._pipeline({}, ())
    with _answering(2, again):
        online._process(pipeline, inputs)

    assert first == ["a1"]
    assert again == ["a2", "a3"]
    assert _held(online.backend) == {
        file: ["processed:a1:0@run1", "processed:a2:0@run2", "processed:a3:0@run2"]
    }


@pytest.mark.parametrize(
    ("saved", "stopped"), [("sub/page.json", "page.json"), ("page.json", "sub/page.json")]
)
def test_a_resume_carries_the_checkpoint_of_a_file_it_reaches_after_saving_another(
    tmp_path, saved, stopped
):
    """Saving one file clears that file's checkpoint rows alone, under the name it is
    stored by, so the file the run stopped in still carries what it answered."""
    online = _Online(tmp_path, stopped)
    inputs = {saved: [rec("b1"), rec("b2")], stopped: [rec("a1"), rec("a2"), rec("a3")]}

    def walk(run: int, sent: list[str], stop_at: str | None = None) -> None:
        for file in (saved, stopped):
            online.file = online.stored_as = file
            online._upstream_wrote(inputs[file])
            _config_, pipeline = online._pipeline({}, ())
            with _answering(run, sent, stop_at=stop_at):
                online._process(pipeline, inputs[file])

    first: list[str] = []
    with pytest.raises(KeyboardInterrupt):
        walk(1, first, stop_at="a2")
    again: list[str] = []
    walk(2, again)

    assert first == ["b1", "b2", "a1"]
    assert again == ["a2", "a3"]
    assert _held(online.backend) == {
        saved: ["processed:b1:0@run1", "processed:b2:0@run1"],
        stopped: ["processed:a1:0@run1", "processed:a2:0@run2", "processed:a3:0@run2"],
    }


def test_a_checkpoint_left_under_the_bare_name_costs_a_resend_and_loses_nothing(tmp_path):
    """What an earlier release left when a run over a nested file was interrupted: its
    answers checkpointed under ``page.json``. The resume does not look there, so it
    answers those records once more."""
    online = _Online(tmp_path, "sub/page.json")
    inputs = [rec("a1"), rec("a2")]
    online._upstream_wrote(inputs)
    answered = RecordEnvelope.build(ACTION, {"answer": "a1:0@run1"}, rec("a1"))
    online.backend.set_disposition(ACTION, "a1", "success")
    online.backend.save_checkpoint_records(
        ACTION, "page.json", [{**answered, "source_guid": "a1", "_state": "processed"}]
    )

    sent: list[str] = []
    _config_, pipeline = online._pipeline({}, ())
    with _answering(2, sent):
        online._process(pipeline, inputs)

    assert sorted(sent) == ["a1", "a2"]
    assert _held(online.backend) == {
        "sub/page.json": ["processed:a1:0@run2", "processed:a2:0@run2"]
    }


class _FirstStageOnline:
    """An online action with no action above it, given one staged file."""

    def __init__(self, tmp_path: Path, file: str) -> None:
        self.backend = SQLiteBackend(str(tmp_path / "first.db"), workflow_name="w")
        self.backend.initialize()
        self.staging = tmp_path / "staging"
        self.target = tmp_path / "target" / ACTION
        self.file = file
        (self.staging / file).parent.mkdir(parents=True)
        self.target.mkdir(parents=True)
        self.sent: list[list[str]] = []

    def stage(self, items: list[str]) -> None:
        path = self.staging / self.file
        if path.suffix == ".csv":
            with path.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["item"])
                writer.writerows([item] for item in items)
        else:
            path.write_text(json.dumps([{"item": item} for item in items]))

    def guid_of(self, item: str) -> str:
        rows = [row for rows in self._rows().values() for row in rows]
        return str(
            next(row["source_guid"] for row in rows if row["content"]["source"]["item"] == item)
        )

    def _rows(self) -> dict[str, list[dict[str, Any]]]:
        self.backend._reconstruction_cache.clear()
        return {
            path: self.backend.read_target_for_rewrite(ACTION, path)
            for path in self.backend.list_target_files(ACTION)
        }

    def run(self, run: int, items: list[str], retry: Sequence[str] = ()) -> dict[str, list[str]]:
        self.stage(items)
        config = _config(
            RunMode.ONLINE,
            {"dependencies": [], "context_scope": {"observe": ["source.*"]}, "idx": 0},
        )
        named = frozenset(self.guid_of(item) for item in retry)
        for guid in named:
            self.backend.clear_disposition(ACTION, record_id=guid)
        sent: list[str] = []
        with _answering(run, sent):
            process_initial_stage(
                InitialStageContext(
                    agent_config=config,
                    agent_name=ACTION,
                    file_path=str(self.staging / self.file),
                    base_directory=str(self.staging),
                    # As the runner hands it: the folder this file's output goes in.
                    output_directory=str((self.target / self.file).parent),
                    idx=0,
                    storage_backend=self.backend,
                    action_configs={ACTION: config},
                    workflow_metadata={},
                    retried_records=named,
                )
            )
        self.sent.append(sorted(sent))
        return _held(self.backend)


@pytest.mark.parametrize("file", STAGED_FILES)
def test_a_repair_of_a_staged_file_keeps_the_rows_it_did_not_name(tmp_path, file):
    first = _FirstStageOnline(tmp_path, file)
    first.run(1, ["a1", "a2", "a3"])

    held = first.run(2, ["a1", "a2", "a3"], retry=["a2"])

    assert first.sent == [["a1", "a2", "a3"], ["a2"]]
    assert held == {
        str(Path(file).with_suffix(".json")): [
            "processed:a1:0@run1",
            "processed:a2:0@run2",
            "processed:a3:0@run1",
        ]
    }


@pytest.mark.parametrize("file", STAGED_FILES)
def test_a_re_run_of_a_staged_file_sends_only_the_input_it_has_not_answered(tmp_path, file):
    """The write clears the file's checkpoint rows by the name it stores the file under.
    A row left under it would read as an answer given after the write, and be asked again."""
    first = _FirstStageOnline(tmp_path, file)
    first.run(1, ["a1", "a2"])

    held = first.run(2, ["a1", "a2", "a3"])

    assert first.sent == [["a1", "a2"], ["a3"]]
    assert held == {
        str(Path(file).with_suffix(".json")): [
            "processed:a1:0@run1",
            "processed:a2:0@run1",
            "processed:a3:0@run2",
        ]
    }


@pytest.fixture
def nested(tmp_path, monkeypatch):
    """The `agac retry` fixture's six records, staged in a subdirectory, through two
    tool actions."""
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs"))
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    (staging / "sub").mkdir(parents=True)
    (staging / "sub" / "pages.json").write_text(
        json.dumps([{"page_content": f"page {i}"} for i in range(RECORDS)])
    )
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + SECOND_ACTION)
    (root / "tools" / WORKFLOW / "tag.py").write_text(TAG_TOOL)
    monkeypatch.chdir(root)
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    return root


@pytest.mark.parametrize("action", ["flatten", "enrich"])
def test_agac_retry_in_a_subdirectory_keeps_every_record_it_did_not_name(nested, action):
    named = _record_ids(nested, action)[1]
    _fail(nested, named, action)

    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--record", named])

    assert result.exit_code == 0, result.output
    assert _stored_records(nested, action) == RECORDS
    assert _stored_records(nested, "enrich") == RECORDS
