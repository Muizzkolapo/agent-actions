"""A repair of an action that mints identities for its output rows.

A repair names the action's *inputs*, and an action minting an identity per
output row holds no row carrying any input's — so subtracting one set from the
other removes nothing, and every stale row is carried beside its replacement.

Driven through the real ``UnifiedProcessor``, ``FileToolStrategy`` and
``SQLiteBackend``: enrichment is one of the stages that mints, so a
strategy-only or gate-only harness shows none of this.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agent_actions.processing.disposition_gate import DispositionGate
from agent_actions.processing.record_helpers import derive_relative_path
from agent_actions.processing.strategies.file_tool import FileToolStrategy
from agent_actions.processing.types import ProcessingContext
from agent_actions.processing.unified import UnifiedProcessor
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.utils.udf_management.registry import FileUDFResult

ACTION = "split"
AGENT_CONFIG = {"kind": "tool", "granularity": "file"}


class _Run:
    """Drives the pipeline as a run does, keeping the output where the next run reads it.

    The tool's output is derived from the records it is actually handed, the way a
    real one's is: a repair narrows the input, so a fixed output list would either
    address rows that are no longer there or reproduce work the run did not do.
    """

    def __init__(self, root: Path, fanout: dict[str, int] | None = None):
        self.root = root
        self.fanout = fanout or {}
        self.backend = SQLiteBackend(str(root / "t.db"), workflow_name="w")
        self.backend.initialize()
        self.seen: list[list[str]] = []

    @property
    def _relative(self) -> str:
        return derive_relative_path(str(self.root / "in" / "f.json"), str(self.root / "out"))

    def __call__(self, records: list[dict], repairing: set[str] = frozenset()) -> list[dict]:
        context = ProcessingContext(agent_config=AGENT_CONFIG, agent_name=ACTION)
        context.source_data = records
        context.storage_backend = self.backend
        context.file_path = str(self.root / "in" / "f.json")
        context.output_directory = str(self.root / "out")

        def _tool(*_args, **kwargs):
            given = kwargs.get("context", [])
            self.seen.append([next(iter(item.values())) for item in given])
            return FileUDFResult(
                outputs=[
                    {"source_index": index, "data": {"p": f"{guid}-{n}"}}
                    for index, item in enumerate(given)
                    for guid in [next(iter(item.values()))]
                    for n in range(self.fanout.get(guid, 1))
                ]
            ), True

        gate = DispositionGate(self.backend, repairing=repairing)
        with patch(
            "agent_actions.processing.strategies.file_tool.run_dynamic_agent", side_effect=_tool
        ):
            output, _stats = UnifiedProcessor(disposition_gate=gate).process(
                list(records), context, FileToolStrategy(), raw_records=list(records)
            )
        self.backend._write_target_raw(ACTION, self._relative, output)
        self.backend._reconstruction_cache.clear()
        return output

    def repair(self, records: list[dict], named: set[str]) -> list[dict]:
        """What ``agac retry`` does: forget the named records, then run narrowed to them."""
        for record_id in named:
            self.backend.clear_disposition(ACTION, record_id=record_id)
        return self(records, repairing=named)

    def stored(self) -> list[dict]:
        self.backend._reconstruction_cache.clear()
        return self.backend.read_target_for_rewrite(ACTION, self._relative)


@pytest.fixture
def run(tmp_path):
    def _make(fanout=None):
        return _Run(tmp_path, fanout)

    return _make


def _records(*guids: str, ancestor: str | None = None) -> list[dict]:
    records = [{"source_guid": g, "content": {"prev": {"id": g}}} for g in guids]
    if ancestor:
        # What an input that was itself minted upstream carries: parent_source_guid
        # is a tracking field, held across every 1:1 stage after the expansion.
        for record in records:
            record["parent_source_guid"] = ancestor
    return records


class TestAnExpansionRepairedByInput:
    """r0 produces two rows, r1 one. Repairing r0 must replace r0's two rows."""

    def test_the_output_does_not_grow(self, run):
        r = run({"r0": 2})
        first = r(_records("r0", "r1"))
        assert len(first) == 3

        r.repair(_records("r0", "r1"), {"r0"})

        assert len(r.stored()) == 3, "r0's stale rows were carried beside its fresh ones"

    def test_a_repeated_repair_does_not_grow_it_further(self, run):
        r = run({"r0": 2})
        r(_records("r0", "r1"))
        r.repair(_records("r0", "r1"), {"r0"})
        r.repair(_records("r0", "r1"), {"r0"})

        assert len(r.stored()) == 3

    def test_the_rows_the_repair_named_are_the_fresh_ones(self, run):
        """Not just the count: the stale pair must be the pair that is gone."""
        r = run({"r0": 2})
        first = r(_records("r0", "r1"))
        stale = {row["source_guid"] for row in first if row.get("parent_source_guid") == "r0"}
        assert len(stale) == 2

        r.repair(_records("r0", "r1"), {"r0"})

        assert stale.isdisjoint({row["source_guid"] for row in r.stored()})

    def test_the_row_of_an_unnamed_input_keeps_its_identity(self, run):
        """The control the fix must not break: r1 was not named, so its row stands."""
        r = run({"r0": 2})
        first = r(_records("r0", "r1"))
        untouched = next(row for row in first if row.get("parent_source_guid") == "r1")

        r.repair(_records("r0", "r1"), {"r0"})

        assert untouched["source_guid"] in {row["source_guid"] for row in r.stored()}


class TestTheSplitterWhoseCountsMatch:
    """615's shape: r0 splits into two, r1 gives one, r2 is dropped. As many rows
    out as records in, so the rule that calls a result an expansion sees none —
    yet ``_reattach_source_guid`` mints for the rows that share a parent."""

    def test_repairing_the_split_input_replaces_only_its_rows(self, run):
        r = run({"r0": 2, "r2": 0})
        first = r(_records("r0", "r1", "r2"))
        assert len(first) == 4

        r.repair(_records("r0", "r1", "r2"), {"r0"})

        assert len(r.stored()) == 4


class TestARepairThatNamesAStoredRow:
    """The mirror of the same mismatch. A minted row's identity is what the
    disposition table holds, so it is what ``--record`` can name — and it matches
    no input, so the run processes nothing while the subtraction drops its row."""

    def test_the_named_row_is_not_deleted(self, run):
        r = run({"r0": 2})
        first = r(_records("r0", "r1"))
        minted = first[0]["source_guid"]

        r.repair(_records("r0", "r1"), {minted})

        assert minted in {row["source_guid"] for row in r.stored()}

    def test_no_row_is_deleted(self, run):
        r = run({"r0": 2})
        first = r(_records("r0", "r1"))

        r.repair(_records("r0", "r1"), {first[0]["source_guid"]})

        assert len(r.stored()) == len(first)


class TestAnInputThatWasItselfExpanded:
    """``parent_source_guid`` is the original pool ancestor, not the immediate
    producer (issue #1022), so rows of a chained expansion name the grandparent
    and cannot be attributed to the input that made them. Nothing here asks for
    that to work — only that it is not made worse, and that it is not silent."""

    def test_no_row_is_lost(self, run):
        r = run({"m0": 2})
        first = r(_records("m0", "m1", ancestor="s0"))
        assert {row.get("parent_source_guid") for row in first} == {"s0"}

        r.repair(_records("m0", "m1", ancestor="s0"), {"m0"})

        assert {row["source_guid"] for row in first} <= {row["source_guid"] for row in r.stored()}

    def test_a_row_it_cannot_attribute_is_reported(self, caplog, run):
        r = run({"m0": 2})
        r(_records("m0", "m1", ancestor="s0"))

        with caplog.at_level("WARNING"):
            r.repair(_records("m0", "m1", ancestor="s0"), {"m0"})

        assert "cannot be attributed" in caplog.text


class TestWhatAOneToOneRepairDoes:
    """The control for the whole change: an action whose rows carry its inputs'
    identities was already right and must stay untouched."""

    def test_the_named_record_is_reprocessed_and_the_other_is_not(self, run):
        r = run()
        r(_records("r0", "r1"))

        r.repair(_records("r0", "r1"), {"r0"})

        assert r.seen[1:] == [["r0"]]
        assert [row["source_guid"] for row in r.stored()] == ["r0", "r1"]
