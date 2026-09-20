"""An input a FILE tool expanded is left unaccounted, and re-split on every run.

Enrichment mints a fresh identity for every output row of an expansion, so each
disposition is keyed by a minted guid and the input that produced them has none.
Carry-forward cannot resolve it either: it reads prior output by ``source_guid``,
which no row of an expansion carries for its input. Closing the gap needs a
per-action record of which input produced a row — ``parent_source_guid`` is the
*original* pool identity, not the immediate producer. Design in issue #1022.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent_actions.processing.disposition_gate import DispositionGate
from agent_actions.processing.record_helpers import derive_relative_path
from agent_actions.processing.strategies.file_tool import FileToolStrategy
from agent_actions.processing.types import ProcessingContext
from agent_actions.processing.unified import UnifiedProcessor
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.utils.udf_management.registry import FileUDFResult

ACTION = "collect_questions"
AGENT_CONFIG = {"kind": "tool", "granularity": "file"}

# Two inputs, three outputs — more out than in, which is what makes it an
# expansion. r0 is split across two rows; r1 produces one.
EXPANSION = [
    {"source_index": 0, "data": {"part": 1}},
    {"source_index": 0, "data": {"part": 2}},
    {"source_index": 1, "data": {"part": 3}},
]

# Strict, so closing the gap turns these into unexpected passes rather than
# quiet greens. Two reasons because they fail at different layers: the row is
# never written, and separately the input is never resolvable for carry-forward.
UNACCOUNTED = pytest.mark.xfail(strict=True, reason="an expanded input leaves no disposition row")
REDONE = pytest.mark.xfail(
    strict=True, reason="carry-forward cannot resolve an expanded input, so it is re-split"
)


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"), workflow_name="w")
    b.initialize()
    return b


def _records(*guids: str, ancestor: str | None = None) -> list[dict]:
    records = [{"source_guid": g, "content": {"prev": {"id": g}}} for g in guids]
    if ancestor:
        # What every record downstream of any expansion carries: parent_source_guid
        # is a tracking field, held across all 1:1 stages.
        for record in records:
            record["parent_source_guid"] = ancestor
    return records


class _Run:
    """Drives the pipeline as a real run does, keeping what it wrote.

    The gate and the persisted output are both required: carry-forward reads the
    action's own prior output, so a harness that does not write it makes every
    record look un-carryable and hides the half about re-splitting.
    """

    def __init__(self, backend, tmp_path):
        self.backend = backend
        self.tmp_path = tmp_path
        self.seen: list[list[str]] = []

    def __call__(self, records: list[dict], outputs: list[dict]) -> list[dict]:
        context = ProcessingContext(agent_config=AGENT_CONFIG, agent_name=ACTION)
        context.source_data = records
        context.storage_backend = self.backend
        context.file_path = str(self.tmp_path / "in" / "f.json")
        context.output_directory = str(self.tmp_path / "out")

        def _tool(*_args, **kwargs):
            self.seen.append([list(item.values())[0] for item in kwargs.get("context", [])])
            return FileUDFResult(outputs=outputs), True

        with patch(
            "agent_actions.processing.strategies.file_tool.run_dynamic_agent", side_effect=_tool
        ):
            output, _stats = UnifiedProcessor(
                disposition_gate=DispositionGate(self.backend)
            ).process(list(records), context, FileToolStrategy(), raw_records=list(records))

        relative = derive_relative_path(context.file_path, context.output_directory)
        self.backend._write_target_raw(ACTION, relative, output)
        return output


@pytest.fixture
def run(backend, tmp_path):
    return _Run(backend, tmp_path)


def _rows(backend) -> list[dict]:
    return backend.get_disposition(ACTION)


def _by_id(backend) -> dict[str, dict]:
    return {r["record_id"]: r for r in _rows(backend)}


class TestAnInputThatWasExpanded:
    @UNACCOUNTED
    def test_the_parent_of_several_rows_has_a_row(self, run, backend):
        run(_records("r0", "r1"), EXPANSION)

        assert "r0" in _by_id(backend)

    @UNACCOUNTED
    def test_the_parent_of_a_single_row_has_one_too(self, run, backend):
        """Every output row is minted on an expansion, not only the split ones, so
        the one-to-one parent loses its identity alongside the split one."""
        run(_records("r0", "r1"), EXPANSION)

        assert "r1" in _by_id(backend)

    @UNACCOUNTED
    def test_every_input_is_accounted_exactly_once(self, run, backend):
        """Cardinality, not membership: one row per input beside the minted ones,
        and never two rows for one input."""
        output = run(_records("r0", "r1"), EXPANSION)
        minted = {o["source_guid"] for o in output}

        rows = _rows(backend)
        assert len(rows) == len(minted) + 2, f"expected one row per input beside the minted: {rows}"
        assert sorted({r["record_id"] for r in rows} - minted) == ["r0", "r1"]


class TestTheParentIsNotRedone:
    """The row is only half of it. A terminal input goes to carry-forward, which
    reads prior output by `source_guid` — an expanded input's identity is on no
    row of it — so it is re-queued and re-split into a fresh set of identities
    while the rows written for the last set stay behind."""

    @REDONE
    def test_an_identical_rerun_does_not_invoke_the_tool(self, run):
        run(_records("r0", "r1"), EXPANSION)
        run(_records("r0", "r1"), EXPANSION)

        assert len(run.seen) == 1, f"the tool ran again on: {run.seen[1:]}"

    @REDONE
    def test_the_children_keep_the_identities_they_were_given(self, run):
        first = run(_records("r0", "r1"), EXPANSION)
        second = run(_records("r0", "r1"), EXPANSION)

        assert [o["source_guid"] for o in second] == [o["source_guid"] for o in first]

    @REDONE
    def test_it_holds_for_an_input_that_was_itself_expanded(self, run):
        """The case that rules out resolving this through `parent_source_guid`: an
        input produced by an upstream expansion passes its *own* ancestor to its
        children, never its own guid, so no row of the output names it."""
        first = run(_records("m0", "m1", ancestor="s0"), EXPANSION)
        # The shape itself, asserted: the children name the grandparent, so no row
        # of the output names m0 or m1 and matching on this field cannot find them.
        assert {o.get("parent_source_guid") for o in first} == {"s0"}

        second = run(_records("m0", "m1", ancestor="s0"), EXPANSION)

        assert [o["source_guid"] for o in second] == [o["source_guid"] for o in first]


class TestWhatMustNotChangeWhileClosingThis:
    """A guard on today's behaviour, for whoever closes the gap above. An attempt
    that ungated the missing-record sweep for expansions broke exactly this."""

    def test_an_input_the_tool_did_not_name_is_left_alone(self, run, backend):
        """A tool may expand while naming only some of what it consumed. The
        framework cannot tell that from a drop, so it claims neither way.

        Both halves are asserted on what a tombstone would create, not on whether
        the input returns: `unprocessed` is not in `TERMINAL_DISPOSITIONS`, so the
        gate re-offers the input with or without one and asserting its return
        could not fail. The harm is the `CASCADE_SKIPPED` state a tombstone row
        carries, which is not resettable downstream.
        """
        output = run(
            _records("r0", "r1"), [{"source_index": 0, "data": {"part": i}} for i in range(3)]
        )

        assert "r1" not in _by_id(backend), "an unnamed input must not be claimed as consumed"
        assert all(o.get("source_guid") != "r1" for o in output), (
            "an unnamed input must not gain a tombstone row of its own"
        )
