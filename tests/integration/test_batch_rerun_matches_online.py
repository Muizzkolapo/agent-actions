"""A batch re-run holds what an online re-run holds, and answers what it answers.

Both run modes are driven from ``ProcessingPipeline.process``, above the fork, against a
real store. Below it everything is the production object except the model: online swaps
the strategy, batch swaps the provider. So the guard, record limit, gate, preparator,
submission, enrichment, collector and finalize all run as they do for a user.

The two files are not always equal. Batch writes a failed row where online refuses to
write at all, and keeps the rows of inputs a record limit holds back. What must never
happen is the reverse, and ``shortfalls`` names each way it could.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.config.types import RunMode
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    InitialStageContext,
    process_initial_stage,
)
from agent_actions.llm.batch.core.batch_constants import BatchStatus, FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.core.batch_models import BatchIdentity, RecoveryContext
from agent_actions.llm.batch.infrastructure.context import (
    BatchContextManager,
    batch_output_name,
)
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.batch.services.processing_recovery import raise_pending_exhaustion
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.exhausted_builder import ExhaustedRecordBuilder
from agent_actions.processing.record_helpers import build_exhausted_tombstone, build_tombstone
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    RecoveryMetadata,
    RetryMetadata,
)
from agent_actions.record.envelope import RecordEnvelope
from agent_actions.record.reasons import EMPTY_OUTPUT
from agent_actions.storage.backend import FAILURE_DISPOSITIONS
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.pipeline import create_processing_pipeline_from_params

ACTION = "write_question"
UPSTREAM = "flatten"
FILE = "page.json"

FILTER = {"guard": {"clause": f"{UPSTREAM}.keep == true", "behavior": "filter"}}
SKIP = {"guard": {"clause": f"{UPSTREAM}.keep == true", "behavior": "skip"}}


@pytest.fixture(autouse=True)
def _only_warnings_are_captured(caplog):
    """A failure here spans many whole runs; at DEBUG its report is megabytes of log."""
    caplog.set_level(logging.WARNING, logger="agent_actions")


def rec(guid: str, **fields: Any) -> dict[str, Any]:
    """An input as an upstream expansion hands it on: a minted child naming its record."""
    return {
        "source_guid": guid,
        "parent_source_guid": "S",
        "producer_source_guids": ["S"],
        "target_id": f"t-{guid}",
        "parent_target_id": "t-S",
        "node_id": f"{UPSTREAM}_{guid}",
        "lineage": [f"{UPSTREAM}_{guid}"],
        "content": {UPSTREAM: {"item": guid, **fields}},
    }


class Answerer:
    """What the model says for one input on one run: a number of rows, or a failure."""

    def __init__(self, shape: dict[Any, Any] | None = None) -> None:
        self.shape = shape or {}

    def __call__(self, guid: str, run: int) -> Any:
        want = self.shape.get((guid, run), self.shape.get(guid, 1))
        if want in ("fail", "exhaust", "empty object"):
            return want
        return [{"answer": f"{guid}:{position}@run{run}"} for position in range(want)]


def _exhausted() -> RecoveryMetadata:
    return RecoveryMetadata(
        retry=RetryMetadata(attempts=3, failures=3, succeeded=False, reason="missing")
    )


def _config(run_mode: RunMode, extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_type": ACTION,
        "name": ACTION,
        "action_name": ACTION,
        "kind": "llm",
        "model_vendor": "openai",
        "model_name": "fake-model",
        "run_mode": run_mode,
        "json_mode": False,
        "prompt": "Write a question.",
        "dependencies": [UPSTREAM],
        "context_scope": {"observe": [f"{UPSTREAM}.*"]},
        "idx": 1,
        "workflow_session_id": "session-1",
        **extra,
    }


def answers(rows: list[dict[str, Any]]) -> list[str]:
    """What each stored row says, in a form both modes produce identically.

    Minted identities differ between the two stores, so an answered row is named by its
    answer (input, position, run) and any other row by its state and identity.
    """
    out = []
    for row in rows:
        mine = (row.get("content") or {}).get(ACTION)
        text = mine.get("answer") if isinstance(mine, dict) else None
        out.append(f"{row.get('_state')}:{text or row.get('source_guid')}")
    return sorted(out)


def _written_twice(rows: list[dict[str, Any]]) -> list[str]:
    guids = [row["source_guid"] for row in rows]
    return sorted({guid for guid in guids if guids.count(guid) > 1})


class _Mode:
    """One run mode with a store of its own."""

    run_mode: RunMode

    def __init__(self, tmp_path: Path, file: str = FILE) -> None:
        name = self.run_mode.value
        self.backend = SQLiteBackend(str(tmp_path / f"{name}.db"), workflow_name="w")
        self.backend.initialize()
        self.base = tmp_path / name / "in"
        self.out = tmp_path / name / "out"
        self.base.mkdir(parents=True)
        self.out.mkdir(parents=True)
        self.file = file
        self.stored_as = file
        self.sent: list[list[str]] = []
        self.raised: list[str | None] = []

    def held(self) -> list[dict[str, Any]]:
        self.backend._reconstruction_cache.clear()
        try:
            return self.backend.read_target_for_rewrite(ACTION, self.stored_as)
        except FileNotFoundError:
            return []

    def everything_held(self) -> list[str]:
        """What the action holds across every file it has stored, not this one alone."""
        self.backend._reconstruction_cache.clear()
        return sorted(
            answer
            for path in self.backend.list_target_files(ACTION)
            for answer in answers(self.backend.read_target_for_rewrite(ACTION, path))
        )

    def _reset(self) -> None:
        """What the executor does to a completed action whose limit or config changed."""
        self.backend.clear_disposition(ACTION)

    def _upstream_wrote(self, inputs: list[dict[str, Any]]) -> None:
        """Store the upstream action's output for this run, as its own run would have."""
        self.backend.save_metadata("execution_order", json.dumps([UPSTREAM, ACTION]))
        self.backend.save_metadata(
            "dependency_graph", json.dumps({UPSTREAM: [], ACTION: [UPSTREAM]})
        )
        rows = [
            {**json.loads(json.dumps(row)), "_delta_mode": "full", "_state": "processed"}
            for row in inputs
        ]
        self.backend._write_target_raw(UPSTREAM, self.stored_as, rows)
        self.backend._reconstruction_cache.clear()

    def failures(self) -> list[str]:
        """The records ``agac retry`` would name."""
        return [
            row["record_id"]
            for disposition in sorted(FAILURE_DISPOSITIONS)
            for row in self.backend.get_disposition(ACTION, disposition=disposition)
        ]

    def _repairing(self, named: Any) -> frozenset[str]:
        """What ``agac retry`` does first: forget the records, then narrow the run to them."""
        for guid in named:
            self.backend.clear_disposition(ACTION, record_id=guid)
        return frozenset(named)

    def _pipeline(self, extra: dict[str, Any], retry: Any):
        config = _config(self.run_mode, extra)
        return config, create_processing_pipeline_from_params(
            action_config=config,
            action_name=ACTION,
            idx=1,
            action_configs={ACTION: config},
            storage_backend=self.backend,
            retried_records=self._repairing(retry),
        )

    def _process(self, pipeline: Any, inputs: list[dict[str, Any]]) -> None:
        try:
            pipeline.process(
                str(self.base / self.file),
                str(self.base),
                # As the runner hands it: the folder this file's output goes in.
                str((self.out / self.file).parent),
                data=json.loads(json.dumps(inputs)),
            )
        except Exception as error:  # recorded, and compared between the modes
            self.raised.append(f"{type(error).__name__}: {error}")
        else:
            self.raised.append(None)


class _Online(_Mode):
    run_mode = RunMode.ONLINE

    def run(
        self,
        run: int,
        inputs: list[dict[str, Any]],
        answer: Answerer | None = None,
        extra: dict[str, Any] | None = None,
        retry: Any = (),
        reset: bool = False,
    ) -> list[str]:
        answer = answer or Answerer()
        taken: list[str] = []
        if reset:
            self._reset()
        self._upstream_wrote(inputs)

        class Strategy:
            def invoke(self, batch: list[dict[str, Any]], context: ProcessingContext):
                results = []
                for record in batch:
                    guid = record["source_guid"]
                    taken.append(guid)
                    said = answer(guid, run)
                    if said in ([], "empty object"):
                        # What the real strategy does with an empty answer (`on_empty`).
                        if context.agent_config.get("on_empty", "warn") == "skip":
                            result = ProcessingResult.skipped(
                                passthrough_data=build_tombstone(
                                    ACTION, record, EMPTY_OUTPUT, source_guid=guid
                                ),
                                reason=EMPTY_OUTPUT,
                                source_guid=guid,
                                input_record=record,
                            )
                        else:
                            result = ProcessingResult.failed(
                                error=f"Empty LLM response for record '{guid}'",
                                source_guid=guid,
                                input_record=record,
                            )
                    elif said == "fail":
                        result = ProcessingResult.failed(
                            error="provider error", source_guid=guid, input_record=record
                        )
                    elif said == "exhaust":
                        result = ProcessingResult.exhausted(
                            error="Retry exhausted after 3 attempts",
                            data=[
                                build_exhausted_tombstone(
                                    ACTION,
                                    record,
                                    ExhaustedRecordBuilder.build_empty_content(
                                        context.agent_config
                                    ),
                                    source_guid=guid,
                                )
                            ],
                            source_guid=guid,
                            recovery_metadata=_exhausted(),
                            source_snapshot=json.loads(json.dumps(record)),
                        )
                    else:
                        data = []
                        for item in said:
                            row = RecordEnvelope.build(ACTION, item, record)
                            row["source_guid"] = guid
                            data.append(row)
                        result = ProcessingResult.success(data=data, source_guid=guid)
                        result.is_expansion = len(data) > 1
                    results.append(result)
                return results

        _config_, pipeline = self._pipeline(extra or {}, retry)
        with patch.object(pipeline, "_select_strategy", return_value=Strategy()):
            self._process(pipeline, inputs)
        self.sent.append(sorted(taken))
        return answers(self.held())


class _Provider:
    """The provider's two calls the submission path makes."""

    vendor_type = "openai"

    def __init__(self) -> None:
        self.submitted: list[list[dict[str, Any]]] = []

    def prepare_tasks(self, tasks: list[dict[str, Any]], config: dict[str, Any]):
        return [{"custom_id": task["target_id"], "body": task} for task in tasks]

    def submit_batch(self, tasks, batch_name, output_directory):
        self.submitted.append(tasks)
        return f"batch-{len(self.submitted)}", BatchStatus.SUBMITTED


class _Batch(_Mode):
    run_mode = RunMode.BATCH

    def __init__(
        self, tmp_path: Path, file: str = FILE, *, clears_batch_state: bool = True
    ) -> None:
        super().__init__(tmp_path, file)
        self.stored_as = batch_output_name(file)
        self.provider = _Provider()
        self.sent_in_order: list[list[str]] = []
        self.clears_batch_state = clears_batch_state

    def run(
        self,
        run: int,
        inputs: list[dict[str, Any]],
        answer: Answerer | None = None,
        extra: dict[str, Any] | None = None,
        retry: Any = (),
        reset: bool = False,
    ) -> list[str]:
        answer = answer or Answerer()
        if reset:
            self._reset()
        # A reset, `agac retry` and `--fresh` each clear this before the action runs
        # again. A plain run over a failed action clears nothing.
        if self.clears_batch_state or reset:
            self.backend.clear_batch_state(ACTION)
        self._upstream_wrote(inputs)

        config, pipeline = self._pipeline(extra or {}, retry)
        before = len(self.provider.submitted)
        with patch(
            "agent_actions.llm.batch.infrastructure.batch_client_resolver."
            "BatchClientResolver.get_for_config",
            return_value=self.provider,
        ):
            self._process(pipeline, inputs)
        if self.raised[-1] is not None or len(self.provider.submitted) == before:
            self.sent.append([])
            self.sent_in_order.append([])
            return answers(self.held())

        self.sent_in_order.append(
            _collect(self.backend, self.provider, config, self.out, self.file, run, answer)
        )
        self.sent.append(sorted(self.sent_in_order[-1]))
        return answers(self.held())


def _collect(
    backend: SQLiteBackend,
    provider: _Provider,
    config: dict[str, Any],
    out: Path,
    name: str,
    run: int,
    answer: Answerer,
    label: Any = lambda row: row.get("source_guid") or row["target_id"],
) -> list[str]:
    """Answer the batch just submitted and finalize it. Returns what was sent, in order.

    A record is answered by its source_guid, or by its target_id where it has none.
    """
    context_map = BatchContextManager.load_batch_context_map(backend, ACTION, name)
    included = {
        custom_id: row
        for custom_id, row in context_map.items()
        if BatchContextMetadata.get_filter_status(row) == FilterStatus.INCLUDED
    }
    submitted = [task["custom_id"] for task in provider.submitted[-1]]
    assert sorted(submitted) == sorted(included)

    results = []
    exhausted: dict[str, Any] = {}
    for custom_id, row in included.items():
        said = answer(label(row), run)
        if said == "exhaust":
            exhausted[custom_id] = _exhausted()
        elif said == "fail":
            results.append(
                BatchResult(custom_id=custom_id, content=None, success=False, error="boom")
            )
        elif said == "empty object":
            results.append(BatchResult(custom_id=custom_id, content={}, success=True))
        else:
            content = said if len(said) != 1 else said[0]
            results.append(BatchResult(custom_id=custom_id, content=content, success=True))

    manager = BatchRegistryManager(backend, ACTION)
    entry = manager.get_batch_job(name)
    assert entry is not None, "submission registered nothing"
    service = BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=BatchContextManager(),
        result_processor=BatchResultStrategy(),
        registry_manager_factory=lambda name: manager,
        workflow_name=ACTION,
        storage_backend=backend,
    )
    context = RecoveryContext(
        service=service,
        manager=manager,
        provider=provider,
        agent_config=dict(config),
        output_directory=str(out),
        action_name=ACTION,
        start_time=0.0,
    )
    service._finalize_batch_output(
        context=context,
        identity=BatchIdentity(batch_id=entry.batch_id, file_name=name, entry=entry),
        batch_results=results,
        context_map=context_map,
        exhausted_recovery=exhausted or None,
    )
    # As the finalisers' callers do: a halt parked during the write is raised after it.
    raise_pending_exhaustion(context)
    return [label(included[custom_id]) for custom_id in submitted]


class _FirstStageBatch:
    """A batch action with no action above it, driven through ``process_initial_stage``."""

    def __init__(self, tmp_path: Path, file: str = FILE) -> None:
        self.backend = SQLiteBackend(str(tmp_path / "first.db"), workflow_name="w")
        self.backend.initialize()
        self.staging = tmp_path / "staging"
        self.target = tmp_path / "target" / ACTION
        self.staging.mkdir(parents=True)
        self.target.mkdir(parents=True)
        self.file = file
        self.file_type_filter: set[str] | None = None
        self.provider = _Provider()
        self.sent: list[list[str]] = []

    def run(
        self,
        run: int,
        staged: list[dict[str, Any]],
        extra: dict[str, Any],
        retried: frozenset[str] = frozenset(),
    ) -> list[str]:
        self.backend.clear_batch_state(ACTION)
        staged_file = self.staging / self.file
        staged_file.parent.mkdir(parents=True, exist_ok=True)
        if staged_file.suffix == ".csv":
            header = list(staged[0])
            lines = [",".join(header)] + [",".join(str(row[k]) for k in header) for row in staged]
            staged_file.write_text("\n".join(lines) + "\n")
        else:
            staged_file.write_text(json.dumps(staged))
        config = _config(
            RunMode.BATCH,
            {"dependencies": [], "context_scope": {"observe": ["source.*"]}, "idx": 0, **extra},
        )
        before = len(self.provider.submitted)
        with patch(
            "agent_actions.llm.batch.infrastructure.batch_client_resolver."
            "BatchClientResolver.get_for_config",
            return_value=self.provider,
        ):
            process_initial_stage(
                InitialStageContext(
                    agent_config=config,
                    agent_name=ACTION,
                    file_path=str(staged_file),
                    base_directory=str(self.staging),
                    # As the runner hands it: the folder this file's output goes in.
                    output_directory=str((self.target / self.file).parent),
                    idx=0,
                    storage_backend=self.backend,
                    action_configs={ACTION: config},
                    workflow_metadata={},
                    retried_records=retried,
                    file_type_filter=self.file_type_filter,
                )
            )
        self.sent.append(
            _collect(
                self.backend,
                self.provider,
                config,
                self.target,
                self.file,
                run,
                Answerer(),
                label=lambda row: row["content"]["source"]["item"],
            )
            if len(self.provider.submitted) > before
            else []
        )
        self.backend._reconstruction_cache.clear()
        try:
            return answers(
                self.backend.read_target_for_rewrite(ACTION, batch_output_name(self.file))
            )
        except FileNotFoundError:
            return []


def compare(
    tmp_path: Path,
    runs: list[Any],
    config: dict[str, Any] | None = None,
    shape: dict[Any, Any] | None = None,
    *,
    clears_batch_state: bool = True,
) -> list[dict[str, Any]]:
    """Run every step through both modes and report what each held and sent.

    A step is a list of inputs (guids or records), or a dict of ``inputs`` with an
    optional ``config`` override for that run, an optional ``reset``, and an optional
    ``retry``: the records a repair names, or ``"failures"`` for whichever online's store
    says failed. Both modes are given the same names, so both run the same repair.
    """
    online = _Online(tmp_path)
    batch = _Batch(tmp_path, clears_batch_state=clears_batch_state)
    answer = Answerer(shape)
    findings = []
    for number, step in enumerate(runs, start=1):
        step = step if isinstance(step, dict) else {"inputs": step}
        inputs = [rec(item) if isinstance(item, str) else item for item in step["inputs"]]
        extra = {**(config or {}), **step.get("config", {})}
        retry = step.get("retry", ())
        if retry == "failures":
            retry = online.failures()
        reset = step.get("reset", False)
        findings.append(
            {
                "run": number,
                "inputs": {record["source_guid"] for record in inputs},
                "online": online.run(number, inputs, answer, extra, retry, reset),
                "batch": batch.run(number, inputs, answer, extra, retry, reset),
                "online_sent": online.sent[-1],
                "batch_sent": batch.sent[-1],
                "online_raised": online.raised[-1],
                "batch_raised": batch.raised[-1],
                "online_twice": _written_twice(online.held()),
                "batch_twice": _written_twice(batch.held()),
            }
        )
    return findings


def _answered(keys: list[str]) -> set[str]:
    """The answers held, as input and position: which run wrote one is not the point."""
    return {key.split("@")[0] for key in keys if key.startswith("processed:")}


def _input_of(key: str) -> str:
    return key.split(":")[1].split("@")[0]


def shortfalls(findings: list[dict[str, Any]]) -> list[str]:
    """Each way batch fell short of online over a sequence. Empty when it never did."""
    found = []
    held_before: set[str] = set()
    paid_for_alone: set[str] = set()
    for run in findings:
        number = run["run"]
        online_sent, batch_sent = set(run["online_sent"]), set(run["batch_sent"])
        held = _answered(run["batch"])
        for answer in sorted(_answered(run["online"]) - held):
            # An online run that raised wrote nothing, so it still holds answers for
            # records that are no input of this run. A batch run that answered
            # something has written this run's file, without them.
            if run["online_raised"] and _input_of(answer) not in run["inputs"]:
                continue
            # An answer batch had, or one both modes were just given. One batch never
            # had is the next check's to find.
            if answer in held_before or _input_of(answer) in online_sent & batch_sent:
                found.append(f"run {number}: online holds {answer}, batch lost it")
        with_a_row = {_input_of(key) for key in run["batch"]}
        for guid in sorted(online_sent - batch_sent - with_a_row):
            found.append(f"run {number}: online answered {guid}, batch neither did nor holds it")
        alone = batch_sent - online_sent
        for guid in sorted(alone & paid_for_alone):
            found.append(f"run {number}: batch paid for {guid} again where online did not")
        paid_for_alone = {guid for guid in alone if f"failed:{guid}" not in run["batch"]}
        if run["batch_raised"] and not run["online_raised"]:
            found.append(f"run {number}: batch raised {run['batch_raised']}")
        for guid in sorted(set(run["batch_twice"]) - set(run["online_twice"])):
            found.append(f"run {number}: batch wrote {guid} twice")
        held_before = held
    return found


MINTED_AGAIN = {
    "upstream_mints_its_children_again_each_run": [["a1", "a2"], ["a3", "a4"], ["a5", "a6"]],
    "a_new_input_joins_ones_already_done": [["a1", "a2"], ["a1", "a2", "a3"]],
    "an_input_leaves_while_another_is_new": [["a1", "a2"], ["a1", "a3"]],
    "an_input_leaves_then_returns_beside_a_new_one": [
        ["a1", "a2"],
        ["a1", "a3"],
        ["a1", "a2", "a4"],
    ],
    "a_completely_new_batch_of_records": [["r1", "r2"], ["r3"]],
    "half_the_children_are_minted_again": [["a1", "a2", "b1"], ["a3", "a4", "b1"]],
    "an_input_leaves_and_nothing_is_left_to_send": [["a1", "a2"], ["a1"]],
    "an_input_leaves_with_nothing_to_send_then_returns": [["a1", "a2"], ["a1"], ["a1", "a2"]],
    "every_input_leaves": [["a1", "a2"], []],
}


@pytest.mark.parametrize("runs", MINTED_AGAIN.values(), ids=MINTED_AGAIN.keys())
def test_batch_leaves_what_online_leaves(tmp_path, runs):
    """With nothing failing and no limit, the two files are the same after every run."""
    for run in compare(tmp_path, runs):
        assert run["batch"] == run["online"], f"run {run['run']}"
        assert run["batch_sent"] == run["online_sent"], f"run {run['run']}"


_PASSES = [rec("a1", keep=True), rec("a2", keep=True)]
_UNCHANGED_WITH_ONE_REFUSED = [*_PASSES, rec("f1", keep=False)]

NEVER_SHORT = {
    "an_input_the_guard_filters_through_an_unchanged_re_run": (
        [_UNCHANGED_WITH_ONE_REFUSED] * 7,
        FILTER,
        None,
    ),
    "an_input_the_guard_skips_through_an_unchanged_re_run": (
        [_UNCHANGED_WITH_ONE_REFUSED] * 5,
        SKIP,
        None,
    ),
    "a_filtered_input_that_later_passes": (
        [_UNCHANGED_WITH_ONE_REFUSED, [*_PASSES, rec("f1", keep=True)]],
        FILTER,
        None,
    ),
    "an_answered_input_that_later_fails_the_guard": (
        [_PASSES, [rec("a1", keep=True), rec("a2", keep=False)], _PASSES],
        FILTER,
        None,
    ),
    "every_input_sent_fails": (
        [["a1", "a2"], ["a3", "a4"], ["a1", "a2"]],
        None,
        {("a3", 2): "fail", ("a4", 2): "fail"},
    ),
    "the_one_input_sent_fails_beside_a_carried_one": (
        [["a1", "a2", "a3"], ["a1", "a4"], ["a1", "a2", "a3"]],
        None,
        {("a4", 2): "fail", ("a2", 3): "fail"},
    ),
    "a_reset_in_which_everything_fails": (
        [["a1", "a2"], {"inputs": ["a1", "a2"], "reset": True}],
        None,
        {("a1", 2): "fail", ("a2", 2): "fail"},
    ),
    "a_reset_in_which_everything_exhausts": (
        [["a1", "a2"], {"inputs": ["a1", "a2"], "reset": True}],
        None,
        {("a1", 2): "exhaust", ("a2", 2): "exhaust"},
    ),
    "a_reset_in_which_one_fails_and_the_guard_now_skips_the_other": (
        [_PASSES, {"inputs": [rec("a1", keep=True), rec("a2", keep=False)], "reset": True}],
        SKIP,
        {("a1", 2): "fail"},
    ),
    "a_repair_of_an_answered_record_that_then_fails": (
        [["a1", "a2"], {"inputs": ["a1", "a2"], "retry": ["a1"]}],
        None,
        {("a1", 2): "fail"},
    ),
    "a_skipped_input_passes_while_the_only_other_one_sent_fails": (
        [
            ["a3", "a2", "a4", "a5", "n1"],
            [rec("a5", keep=False), rec("a1", keep=False), "a3"],
            [rec("a5", keep=False), "a1", "a2"],
        ],
        SKIP,
        {"a2": 2, ("a2", 3): "fail"},
    ),
    "a_repair_run_while_an_input_is_absent": (
        [
            ["a1", "a2", "a3"],
            {"inputs": ["a2", "a3"], "retry": ["a2"]},
            {"inputs": ["a1", "a2", "a3"], "retry": ["a3"]},
        ],
        None,
        {("a2", 1): "fail"},
    ),
    "a_repair_whose_named_record_the_guard_now_filters": (
        [_PASSES, {"inputs": [rec("a1", keep=True), rec("a2", keep=False)], "retry": "failures"}],
        FILTER,
        {("a2", 1): "exhaust"},
    ),
    "an_exhausted_input_leaves_and_returns": (
        [["a1", "a2"], ["a1"], ["a1", "a2"], ["a1", "a2"]],
        None,
        {("a2", 1): "exhaust"},
    ),
    "a_limit_of_one_then_none_then_one_then_none": (
        [
            {"inputs": ["a1", "a2", "a3", "a4"], "config": {"record_limit": 1}},
            ["a1", "a2", "a3", "a4"],
            {"inputs": ["a1", "a2", "a3", "a4"], "config": {"record_limit": 1}},
            ["a1", "a2", "a3", "a4"],
        ],
        None,
        {"a2": 3},
    ),
    "an_expanding_input_changes_how_many_rows_it_gives": (
        [["a1", "a2"], ["a2"], ["a1", "a2"]],
        None,
        {"a1": 3, ("a1", 3): 2},
    ),
}


@pytest.mark.parametrize("case", NEVER_SHORT.values(), ids=NEVER_SHORT.keys())
def test_batch_never_falls_short_of_online(tmp_path, case):
    runs, config, shape = case

    assert shortfalls(compare(tmp_path, runs, config, shape)) == []


def _random_sequence(
    rng: random.Random, *, guard: bool, limits: bool, retries: bool, resets: bool = False
):
    """Three to six runs over inputs that come, go, expand, fail and flip at the guard."""
    known = [f"a{i}" for i in range(1, 6)]
    shape: dict[Any, Any] = {}
    for guid in known:
        roll = rng.random()
        if roll < 0.25:
            shape[guid] = rng.choice([2, 3])
        elif roll < 0.30:
            shape[guid] = 0
    passes = dict.fromkeys(known, True)
    runs = []
    for number in range(1, rng.randint(3, 6) + 1):
        if rng.random() < 0.2:
            guids = [f"g{number}_{i}" for i in range(rng.randint(1, 3))]
        else:
            guids = [guid for guid in known if rng.random() < 0.65]
            if rng.random() < 0.25:
                guids.append(f"n{number}")
        rng.shuffle(guids)
        for guid in guids:
            if guard and rng.random() < 0.2:
                passes[guid] = not passes.get(guid, True)
            roll = rng.random()
            if roll < 0.08:
                shape[(guid, number)] = "fail"
            elif roll < 0.11:
                shape[(guid, number)] = "exhaust"
        step: dict[str, Any] = {
            "inputs": [rec(guid, keep=passes.get(guid, True)) for guid in guids]
        }
        if limits and rng.random() < 0.4:
            step["config"] = {"record_limit": rng.choice([1, 2, 3])}
        if retries and number > 1 and rng.random() < 0.4:
            step["retry"] = "failures"
        elif resets and number > 1 and rng.random() < 0.5:
            step["reset"] = True
        runs.append(step)
    return runs, shape


FAMILIES = {
    "inputs_come_and_go": ({}, {}),
    "under_a_record_limit": ({}, {"limits": True}),
    "behind_a_filtering_guard": (FILTER, {"guard": True}),
    "behind_a_skipping_guard": (SKIP, {"guard": True}),
    "a_filtering_guard_under_a_limit": (FILTER, {"guard": True, "limits": True}),
    "reset_before_some_runs": ({}, {"resets": True}),
    "reset_behind_a_skipping_guard": (SKIP, {"guard": True, "resets": True}),
    "with_repairs_of_what_failed": ({}, {"retries": True}),
    "repairs_behind_a_filtering_guard": (FILTER, {"guard": True, "retries": True}),
}


def _short_sequences(tmp_path: Path, family: str, **how: Any) -> dict[int, list[str]]:
    config, features = FAMILIES[family]
    features = {"guard": False, "limits": False, "retries": False, **features}
    short = {}
    for seed in range(40):
        runs, shape = _random_sequence(random.Random(seed), **features)
        where = tmp_path / str(seed)
        where.mkdir()
        if found := shortfalls(compare(where, runs, config, shape, **how)):
            short[seed] = found
    return short


@pytest.mark.parametrize("family", FAMILIES.keys())
def test_no_random_sequence_leaves_batch_short_of_online(tmp_path, family):
    assert _short_sequences(tmp_path, family) == {}


@pytest.mark.parametrize("family", ["inputs_come_and_go", "behind_a_filtering_guard"])
def test_nor_does_one_run_plainly_with_the_last_batch_job_left_on_record(tmp_path, family):
    """Only a reset, a repair and `--fresh` clear batch state; a plain run does not."""
    assert _short_sequences(tmp_path, family, clears_batch_state=False) == {}


def test_a_failed_batch_action_run_again_is_submitted_again(tmp_path):
    """Its job finished and was collected, so it is no reason to skip the file."""
    batch = _Batch(tmp_path, clears_batch_state=False)
    batch.run(1, [rec("a1"), rec("a2")], Answerer({("a1", 1): "fail", ("a2", 1): "fail"}))

    held = batch.run(2, [rec("a1"), rec("a2")])

    assert batch.sent[1] == ["a1", "a2"]
    assert held == ["processed:a1:0@run2", "processed:a2:0@run2"]


def test_a_one_to_one_action_below_an_expansion_stays_at_its_input_size(tmp_path):
    """#1155, stated on its own: 2, 2, 2 where it was 2, 4, 6."""
    batch = _Batch(tmp_path)

    sizes = [len(batch.run(n, [rec(f"a{2 * n - 1}"), rec(f"a{2 * n}")])) for n in range(1, 4)]

    assert sizes == [2, 2, 2]


def test_an_input_called_done_whose_row_is_gone_is_answered_again(tmp_path):
    """Online re-queues it; left out, batch would never answer it again."""
    batch = _Batch(tmp_path)
    batch.run(1, [rec("a1"), rec("a2")])
    batch.run(2, [rec("a1"), rec("a3")])

    held = batch.run(3, [rec("a1"), rec("a2"), rec("a4")])

    assert batch.sent[2] == ["a2", "a4"]
    assert held == ["processed:a1:0@run1", "processed:a2:0@run3", "processed:a4:0@run3"]


def test_inputs_answered_again_are_sent_in_the_order_the_input_holds_them(tmp_path):
    batch = _Batch(tmp_path)
    batch.run(1, [rec("a1"), rec("a2"), rec("a3")])
    batch.run(2, [rec("a2"), rec("x1")])

    batch.run(3, [rec("a3"), rec("n1"), rec("a1"), rec("a2"), rec("n2")])

    assert batch.sent_in_order[2] == ["a3", "n1", "a1", "n2"]


@pytest.mark.parametrize("config", [FILTER, SKIP], ids=["filtered", "skipped"])
def test_a_file_in_a_subdirectory_holds_each_answer_once(tmp_path, config):
    """Its output and the write made when nothing is sent were stored under two names."""
    batch = _Batch(tmp_path, "sub/page.json")
    batch.run(1, _UNCHANGED_WITH_ONE_REFUSED, extra=config)

    batch.run(2, _UNCHANGED_WITH_ONE_REFUSED, extra=config)

    answered = [row for row in batch.everything_held() if row.startswith("processed:")]
    assert answered == ["processed:a1:0@run1", "processed:a2:0@run1"]
    assert batch.backend.list_target_files(ACTION) == ["sub/page.json"]


def test_a_first_stage_action_keeps_its_answers_when_nothing_is_left_to_send(tmp_path):
    """The same write, reached from staging: no action above this one hands it rows."""
    staged = [
        {"item": "a1", "keep": True},
        {"item": "a2", "keep": True},
        {"item": "f1", "keep": False},
    ]
    guard = {"guard": {"clause": "source.keep == true", "behavior": "filter"}}
    batch = _FirstStageBatch(tmp_path)
    first = batch.run(1, staged, guard)

    again = batch.run(2, staged, guard)

    assert first == ["processed:a1:0@run1", "processed:a2:0@run1"]
    assert again == first
    assert batch.sent == [["a1", "a2"], []]


EMPTIED = {
    "on_a_plain_run": [["a1", "a2"], []],
    "after_a_reset": [["a1", "a2"], {"inputs": [], "reset": True}],
    "and_then_filled_again": [["a1", "a2"], [], ["a1", "a2"]],
}


@pytest.mark.parametrize("runs", EMPTIED.values(), ids=EMPTIED.keys())
def test_a_file_whose_input_is_now_empty_holds_nothing_as_online(tmp_path, runs):
    """The action above holds nothing for the file, or the runner dropped every record
    of it a guard filtered upstream. Online stores the file empty. A row kept is built
    from a record that is gone, and every action below reads it."""
    for run in compare(tmp_path, runs):
        assert run["batch"] == run["online"], f"run {run['run']}"
        assert run["batch_sent"] == run["online_sent"], f"run {run['run']}"


@pytest.mark.parametrize("file", ["sub/page.json", "page.txt"])
def test_a_file_whose_input_is_now_empty_is_stored_empty_under_its_one_name(tmp_path, file):
    """Finalize stores the file under this name; written under another, the old rows
    stay beside an empty file."""
    batch = _Batch(tmp_path, file)
    batch.run(1, [rec("a1"), rec("a2")])

    held = batch.run(2, [])

    assert held == []
    assert batch.backend.list_target_files(ACTION) == [batch.stored_as]


def test_a_file_whose_every_input_is_done_keeps_its_rows(tmp_path):
    """Nothing is sent here either, but each row answers for an input still there."""
    batch = _Batch(tmp_path)
    first = batch.run(1, [rec("a1"), rec("a2")])

    again = batch.run(2, [rec("a1"), rec("a2")])

    assert batch.sent[1] == []
    assert again == first


def test_a_repair_that_finds_its_file_empty_keeps_its_rows(tmp_path):
    """A repair answers what it named, and online carries every row it did not name."""
    first, repaired = compare(tmp_path, [["a1", "a2"], {"inputs": [], "retry": ["a1"]}])

    assert repaired["online"] == first["online"]
    assert repaired["batch"] == first["batch"]


def test_a_first_stage_file_emptied_in_staging_holds_nothing(tmp_path):
    """Online stores it empty: nothing staged is left for a row to answer for."""
    batch = _FirstStageBatch(tmp_path)
    batch.run(1, [{"item": "a1"}, {"item": "a2"}], {})

    held = batch.run(2, [], {})

    assert held == []
    assert batch.sent[1] == []


PREPARED = {"prompt": f"Write a question about {{{{ {UPSTREAM}.topic }}}}."}


@pytest.mark.parametrize("guard", [SKIP, FILTER], ids=["skipping", "filtering"])
def test_a_reset_where_the_one_record_left_cannot_be_prepared_replaces_no_answer(tmp_path, guard):
    """Nothing is sent and a record failed, so online raises before it writes, and the
    answers stored under the tombstones and the failure row stand."""
    names = ["s1", "s2", "s3", "s4", "s5", "p6"]
    batch = _Batch(tmp_path)
    first = batch.run(
        1, [rec(name, keep=True, topic="dbt") for name in names], extra={**guard, **PREPARED}
    )

    refused = [rec(name, keep=False, topic="dbt") for name in names[:5]] + [rec("p6", keep=True)]
    held = batch.run(2, refused, extra={**guard, **PREPARED}, reset=True)

    assert first == [f"processed:{name}:0@run1" for name in sorted(names)]
    assert [row for row in held if row.startswith("processed:")] == first
    assert batch.sent[1] == []


def test_a_record_that_cannot_be_prepared_is_stored_as_a_failure(tmp_path):
    """Online marks it failed. Stored as a guard skip, the output says the guard turned
    away a record the guard passed, and nothing that reads row state sees a failure."""
    from agent_actions.storage.backend import DISPOSITION_FAILED

    batch = _Batch(tmp_path)
    turned_away = [rec(name, keep=False, topic="dbt") for name in ("s1", "s2", "s3", "s4", "s5")]

    held = batch.run(1, [*turned_away, rec("p6", keep=True)], extra={**SKIP, **PREPARED})

    assert held == ["failed:p6", *(f"guard_skipped:s{n}" for n in range(1, 6))]
    (failed,) = batch.backend.get_disposition(ACTION, disposition=DISPOSITION_FAILED)
    assert failed["record_id"] == "p6"
    assert "topic" in failed["reason"], "the reason is the error itself, as online records it"


def test_a_record_that_cannot_be_prepared_is_not_flagged_as_a_skip(tmp_path):
    batch = _Batch(tmp_path)
    turned_away = [rec(f"s{n}", keep=False, topic="dbt") for n in range(1, 6)]
    batch.run(1, [*turned_away, rec("p6", keep=True)], extra={**SKIP, **PREPARED})

    (failed,) = [row for row in batch.held() if row["source_guid"] == "p6"]

    assert [key for key in failed["metadata"] if key.startswith("skipped_by")] == []


def test_a_record_blocked_upstream_is_stored_as_blocked_when_nothing_is_sent(tmp_path):
    """The action above failed it, so this one never looked at it. Stored as a guard skip
    it reads as a record this action passed over, and the action below processes it."""
    batch = _Batch(tmp_path)
    blocked = {**rec("u1", keep=True), "_state": "failed"}

    held = batch.run(1, [rec("s1", keep=False), blocked], extra=SKIP)

    assert held == ["cascade_skipped:u1", "guard_skipped:s1"]
    (row,) = [row for row in batch.held() if row["source_guid"] == "u1"]
    assert row["_tombstone_reason"] == "upstream_unprocessed"


EMPTY = pytest.mark.parametrize(
    "empty", [0, "empty object"], ids=["an_empty_list", "an_empty_object"]
)


@EMPTY
def test_an_empty_answer_is_a_failure_by_default(tmp_path, empty):
    """`on_empty` defaults to warn. Counted as a success, the record holds no row and a
    done disposition, and nothing says the model returned nothing."""
    from agent_actions.storage.backend import DISPOSITION_FAILED

    batch = _Batch(tmp_path)

    held = batch.run(1, [rec("a1"), rec("a2")], Answerer({"a1": empty}))

    assert held == ["failed:a1", "processed:a2:0@run1"]
    (failed,) = batch.backend.get_disposition(ACTION, disposition=DISPOSITION_FAILED)
    assert (failed["record_id"], failed["reason"]) == ("a1", "Empty LLM response for record 'a1'")


@EMPTY
def test_an_empty_answer_is_a_tombstone_where_the_action_says_skip(tmp_path, empty):
    batch = _Batch(tmp_path)

    batch.run(1, [rec("a1"), rec("a2")], Answerer({"a1": empty}), {"on_empty": "skip"})

    (row,) = [row for row in batch.held() if row["source_guid"] == "a1"]
    assert (row["_state"], row["_tombstone_reason"]) == ("guard_skipped", "empty_output")
    assert row["content"][ACTION] is None


@EMPTY
def test_an_empty_answer_halts_the_action_where_it_says_error_after_the_write(tmp_path, empty):
    """A batch has one write, and the other answers are in it: raised before it, the halt
    would take them down too."""
    from agent_actions.errors.processing import EmptyOutputError

    batch = _Batch(tmp_path)

    with pytest.raises(EmptyOutputError, match="on_empty=error"):
        batch.run(1, [rec("a1"), rec("a2")], Answerer({"a1": empty}), {"on_empty": "error"})

    assert answers(batch.held()) == ["failed:a1", "processed:a2:0@run1"]


def test_no_halt_is_raised_where_no_answer_was_empty(tmp_path):
    batch = _Batch(tmp_path)

    held = batch.run(1, [rec("a1"), rec("a2")], extra={"on_empty": "error"})

    assert held == ["processed:a1:0@run1", "processed:a2:0@run1"]


@pytest.mark.parametrize("on_empty", ["warn", "skip"])
def test_an_empty_answer_leaves_batch_where_it_leaves_online(tmp_path, on_empty):
    """Through a re-run too: a failure is sent again, a tombstone is not."""
    runs = [["a1", "a2"], ["a1", "a2"], ["a1", "a2", "a3"]]

    for run in compare(tmp_path, runs, {"on_empty": on_empty}, {"a1": 0}):
        assert run["batch"] == run["online"], f"run {run['run']}"
        assert run["batch_sent"] == run["online_sent"], f"run {run['run']}"


def test_a_filtered_input_costs_no_submission_and_no_stored_answer(tmp_path):
    """Its disposition says done and it holds no row, by design: nothing is missing."""
    batch = _Batch(tmp_path)
    first = batch.run(1, _UNCHANGED_WITH_ONE_REFUSED, extra=FILTER)

    again = [batch.run(n, _UNCHANGED_WITH_ONE_REFUSED, extra=FILTER) for n in (2, 3, 4)]

    assert first == ["processed:a1:0@run1", "processed:a2:0@run1"]
    assert again == [first] * 3
    assert len(batch.provider.submitted) == 1


_NOW_FILTERED = [rec("a1", keep=True), rec("a2", keep=False)]

GUARD_NOW_FILTERS = {
    "one_answered_input": ([_PASSES, {"inputs": _NOW_FILTERED, "reset": True}], None),
    "every_answered_input": (
        [_PASSES, {"inputs": [rec("a1", keep=False), rec("a2", keep=False)], "reset": True}],
        None,
    ),
    "an_input_that_gave_several_rows": (
        [_PASSES, {"inputs": _NOW_FILTERED, "reset": True}],
        {"a2": 2},
    ),
    "the_input_a_repair_names": (
        [_PASSES, {"inputs": _NOW_FILTERED, "retry": "failures"}],
        {("a2", 1): "exhaust"},
    ),
    "a_repair_that_also_sends_another_named_input": (
        [
            [rec("a1", keep=True), rec("a2", keep=True), rec("a3", keep=True)],
            {
                "inputs": [rec("a1", keep=True), rec("a2", keep=False), rec("a3", keep=True)],
                "retry": "failures",
            },
        ],
        {("a2", 1): "exhaust", ("a3", 1): "exhaust"},
    ),
}


@pytest.mark.parametrize("case", GUARD_NOW_FILTERS.values(), ids=GUARD_NOW_FILTERS.keys())
def test_an_input_the_guard_now_filters_holds_no_row_as_online(tmp_path, case):
    """Editing the guard resets the action, so every input reaches it again. A row
    carried for one it filters is an answer to a record the guard now excludes, and
    every action below reads it."""
    runs, shape = case

    for run in compare(tmp_path, runs, FILTER, shape):
        assert run["batch"] == run["online"], f"run {run['run']}"
        assert run["batch_sent"] == run["online_sent"], f"run {run['run']}"


def test_a_run_that_failed_and_answered_nothing_keeps_what_a_filtered_input_held(tmp_path):
    """Online raises before it writes, so the filtered input's row stays until a run
    that writes, whether or not that row was an answer."""
    runs = [_PASSES, {"inputs": _NOW_FILTERED, "reset": True}, _NOW_FILTERED]
    shape = {("a2", 1): "exhaust", ("a1", 2): "fail"}

    findings = compare(tmp_path, runs, FILTER, shape)

    assert "exhausted:a2" in findings[1]["online"]
    for run in findings:
        assert run["batch"] == run["online"], f"run {run['run']}"


def test_a_repair_the_guard_turns_away_leaves_every_answer_in_place(tmp_path):
    """Nothing is left to send, and what is written in its place must not be nothing."""
    batch = _Batch(tmp_path)
    batch.run(1, _PASSES, Answerer({"a2": "exhaust"}), FILTER)

    held = batch.run(2, [rec("a1", keep=True), rec("a2", keep=False)], extra=FILTER, retry=["a2"])

    assert "processed:a1:0@run1" in held
    assert batch.sent[1] == []


def test_inputs_minted_again_and_skipped_every_run_do_not_pile_up(tmp_path):
    """The write made when nothing is sent follows the inputs too: 2, 2, 2, not 2, 4, 6."""
    batch = _Batch(tmp_path)

    sizes = [
        len(
            batch.run(
                n, [rec(f"s{2 * n - 1}", keep=False), rec(f"s{2 * n}", keep=False)], extra=SKIP
            )
        )
        for n in range(1, 4)
    ]

    assert sizes == [2, 2, 2]


def test_a_run_whose_every_answer_fails_keeps_the_stored_answers(tmp_path):
    """Online raises before it writes; here the failures are written beside them."""
    batch = _Batch(tmp_path)
    batch.run(1, [rec("a1"), rec("a2")])

    held = batch.run(2, [rec("a3"), rec("a4")], Answerer({"a3": "fail", "a4": "fail"}))

    assert held == ["failed:a3", "failed:a4", "processed:a1:0@run1", "processed:a2:0@run1"]


def test_a_run_that_answers_something_leaves_out_what_is_not_its_input(tmp_path):
    """The other edge of the one above: one answer is enough to make it this run's file."""
    batch = _Batch(tmp_path)
    batch.run(1, [rec("a1"), rec("a2")])

    held = batch.run(2, [rec("a3"), rec("a4")], Answerer({"a4": "fail"}))

    assert held == ["failed:a4", "processed:a3:0@run2"]


def test_a_repair_keeps_the_rows_of_an_input_absent_from_it(tmp_path):
    """A repair answers what it named and nothing else, so no other row is its to drop."""
    batch = _Batch(tmp_path)
    batch.run(1, [rec("a1"), rec("a2"), rec("a3")], Answerer({("a2", 1): "fail"}))

    held = batch.run(2, [rec("a2"), rec("a3")], retry=["a2"])

    assert held == ["processed:a1:0@run1", "processed:a2:0@run2", "processed:a3:0@run1"]


def test_a_repair_does_not_read_an_earlier_runs_inputs_as_its_own(tmp_path):
    """Run 2 answered nothing, so the file holds more than the inputs it recorded."""
    batch = _Batch(tmp_path, clears_batch_state=False)
    batch.run(1, [rec("a1"), rec("a2")])
    batch.run(2, [rec("a3")], Answerer({("a3", 2): "fail"}))

    held = batch.run(3, [rec("a3")], retry=["a3"])

    assert held == ["processed:a1:0@run1", "processed:a2:0@run1", "processed:a3:0@run3"]


def test_an_ordinary_run_after_a_repair_goes_back_to_its_own_inputs(tmp_path):
    """The repair recorded no inputs; that must not outlive it."""
    batch = _Batch(tmp_path)
    batch.run(1, [rec("a1"), rec("a2"), rec("a3")], Answerer({("a2", 1): "fail"}))
    batch.run(2, [rec("a2"), rec("a3")], retry=["a2"])

    held = batch.run(3, [rec("a2"), rec("a4")])

    assert held == ["processed:a2:0@run2", "processed:a4:0@run3"]


@pytest.mark.parametrize("file", ["page.json", "page.txt", "page.jsonl", "page.v2.json", "page"])
def test_a_done_input_is_found_whatever_the_input_file_is_called(tmp_path, file):
    """The output is stored under one name and looked up under the same one."""
    batch = _Batch(tmp_path, file)
    first = batch.run(1, [rec("a1"), rec("a2")])

    again = batch.run(2, [rec("a1"), rec("a2"), rec("a3")])

    assert first == ["processed:a1:0@run1", "processed:a2:0@run1"]
    assert batch.sent[1] == ["a3"]
    assert again == [*first, "processed:a3:0@run2"]
