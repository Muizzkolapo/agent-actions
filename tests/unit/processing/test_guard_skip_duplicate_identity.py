"""A guard-skipped record's identity is written once, not twice (#1082).

The guard runs *above* the per-record gate, so a guard-skipped record never reaches
``DispositionGate.filter`` and is absent from every id the run hands carry-forward.
A stored merge row keyed on that record while naming a *carried* input still passes
the producer test in ``build_carry_forward``, so it is handed back — beside the
tombstone the guard has just written for the same identity. Nothing detects it:
``missing`` is empty, so nothing is re-queued either.

Measured across consecutive runs read back through ``read_target_for_rewrite``,
because the duplicate is stable rather than accumulating and an in-memory
assertion on one run cannot tell the two apart. The fix must also not simply drop
the merge row: its content answers for the carried input too, and the run does not
re-invoke the tool on its own.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from agent_actions.processing.disposition_gate import DispositionGate
from agent_actions.processing.record_helpers import derive_relative_path
from agent_actions.processing.strategies.file_tool import FileToolStrategy
from agent_actions.processing.types import ProcessingContext
from agent_actions.processing.unified import UnifiedProcessor
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.utils.udf_management.registry import FileUDFResult

ACTION = "fold_rows"
AGENT_CONFIG: dict[str, Any] = {
    "kind": "tool",
    "granularity": "file",
    "guard": {"clause": "score > 50", "behavior": "skip"},
}

MERGED = ("r1", "r2")


def _records(*, skip_r1: bool) -> list[dict[str, Any]]:
    """Three inputs; only r1's guarded field moves, exactly as #1082 measured it."""
    scores = {"r0": 90, "r1": 10 if skip_r1 else 90, "r2": 90}
    return [
        {"source_guid": guid, "content": {"prev": {"id": guid}, "score": scores[guid]}}
        for guid in ("r0", "r1", "r2")
    ]


def _fold(given: list[str]) -> list[dict[str, Any]]:
    """r0 passes through; r1 and r2 fold into one row, which keys itself on r1.

    ``source_index`` as a list is the many-to-one shape: the row takes the first
    input's identity and names the rest as ``producer_source_guids``.
    """
    outputs: list[dict[str, Any]] = []
    folded = [i for i, guid in enumerate(given) if guid in MERGED]
    if folded:
        outputs.append(
            {
                "source_index": folded if len(folded) > 1 else folded[0],
                "data": {"out": "fold:" + "+".join(given[i] for i in folded)},
            }
        )
    outputs.extend(
        {"source_index": i, "data": {"out": "r0-0"}} for i, guid in enumerate(given) if guid == "r0"
    )
    return outputs


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "t.db"), workflow_name="w")
    store.initialize()
    return store


class _Run:
    """Drives the pipeline as a real run does, keeping what it wrote.

    Returns what the *next* run will read — the rows as
    ``read_target_for_rewrite`` reconstructs them, not the in-memory output.
    """

    def __init__(self, backend: SQLiteBackend, tmp_path) -> None:
        self.backend = backend
        self.tmp_path = tmp_path
        self.seen: list[list[str]] = []

    def __call__(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        context = ProcessingContext(agent_config=AGENT_CONFIG, agent_name=ACTION)
        context.source_data = records
        context.storage_backend = self.backend
        context.file_path = str(self.tmp_path / "in" / "f.json")
        context.output_directory = str(self.tmp_path / "out")

        def _tool(*_args, **kwargs):
            given = [item["id"] for item in kwargs.get("context", [])]
            self.seen.append(given)
            return FileUDFResult(outputs=_fold(given)), True

        with patch(
            "agent_actions.processing.strategies.file_tool.run_dynamic_agent", side_effect=_tool
        ):
            output, _stats = UnifiedProcessor(
                disposition_gate=DispositionGate(self.backend)
            ).process(list(records), context, FileToolStrategy(), raw_records=list(records))

        relative = derive_relative_path(context.file_path, context.output_directory)
        self.backend.write_target(
            ACTION,
            relative,
            [{**row, "_state": "processed", "_schema_version": 1} for row in output],
        )
        # The reconstruction cache has to be dropped between runs or a later run
        # reads the first run's rows back instead of what was just written.
        self.backend._reconstruction_cache.clear()
        return self.backend.read_target_for_rewrite(ACTION, relative)


@pytest.fixture
def run(backend, tmp_path):
    return _Run(backend, tmp_path)


def _guids(rows: list[dict[str, Any]]) -> list[str]:
    return [row["source_guid"] for row in rows]


def _settle(run: _Run) -> list[list[str]]:
    """One run with every input passing, then three with r1 guard-skipped."""
    run(_records(skip_r1=False))
    return [_guids(run(_records(skip_r1=True))) for _ in range(3)]


class TestTheGuardedRecordIsWrittenOnce:
    def test_no_run_stores_two_rows_under_one_identity(self, run):
        """The duplicate is stable from the first skipping run, not cumulative, so
        every run is checked rather than only the last."""
        per_run = _settle(run)

        duplicated = [
            (index + 2, guids)
            for index, guids in enumerate(per_run)
            if len(guids) != len(set(guids))
        ]
        assert not duplicated, f"an identity was stored twice: {duplicated}"

    def test_the_guarded_record_keeps_exactly_one_row(self, run):
        per_run = _settle(run)

        assert [guids.count("r1") for guids in per_run] == [1, 1, 1]


class TestTheMergedInputIsNotLost:
    """The trap in every earlier attempt: refusing the merge row without rebuilding
    it takes the carried input's content with it, and the run never re-invokes the
    tool on its own."""

    def test_the_carried_input_still_has_a_row(self, run):
        per_run = _settle(run)

        assert [("r2" in guids) for guids in per_run] == [True, True, True]

    def test_the_input_whose_row_was_refused_is_re_queued(self, run):
        """Re-queued and re-folded, rather than silently dropped — `missing` is the
        designed route back and the caller extends `to_process` from it."""
        run(_records(skip_r1=False))
        run(_records(skip_r1=True))

        assert run.seen == [["r0", "r1", "r2"], ["r2"]]

    def test_the_rebuilt_row_holds_only_the_input_the_guard_let_through(self, run):
        """r1 was skipped this run, so its content has no business in the fold."""
        run(_records(skip_r1=False))
        stored = run(_records(skip_r1=True))

        folded = [row for row in stored if row["source_guid"] == "r2"]
        assert [row["content"][ACTION]["out"] for row in folded] == ["fold:r2"]


class TestTheRunSettles:
    def test_the_tool_is_not_invoked_again_once_the_row_is_rebuilt(self, run):
        """A rebuild every run would mean the replacement row is never found again,
        which is the same loss wearing a different shape."""
        _settle(run)

        assert run.seen == [["r0", "r1", "r2"], ["r2"]]

    def test_the_untouched_record_keeps_its_answer_throughout(self, run):
        run(_records(skip_r1=False))
        answers = []
        for _ in range(3):
            stored = run(_records(skip_r1=True))
            answers.append(
                [row["content"][ACTION]["out"] for row in stored if row["source_guid"] == "r0"]
            )

        assert answers == [["r0-0"], ["r0-0"], ["r0-0"]]
