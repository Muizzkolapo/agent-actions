"""An input a FILE tool expanded is accounted for, and not re-split on a rerun.

Enrichment mints a fresh identity for every output row of an expansion, so no row
carries the input's own ``source_guid``: the input needs a disposition row, and
carry-forward needs to find the rows it produced. ``producer_source_guids`` closes
the second half — not ``parent_source_guid``, which is the pool ancestor and names
the grandparent once an input has itself been expanded.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.processing.disposition_gate import DispositionGate, build_carry_forward
from agent_actions.processing.enrichment import LineageEnricher
from agent_actions.processing.record_helpers import derive_relative_path
from agent_actions.processing.strategies.file_tool import FileToolStrategy
from agent_actions.processing.types import ProcessingContext, ProcessingResult
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

    def __call__(self, records: list[dict], outputs) -> list[dict]:
        context = ProcessingContext(agent_config=AGENT_CONFIG, agent_name=ACTION)
        context.source_data = records
        context.storage_backend = self.backend
        context.file_path = str(self.tmp_path / "in" / "f.json")
        context.output_directory = str(self.tmp_path / "out")

        def _tool(*_args, **kwargs):
            given = [list(item.values())[0] for item in kwargs.get("context", [])]
            self.seen.append(given)
            # Callable when the shape depends on what the run was handed: a rerun
            # that carries correctly gets a shorter input, and a fixed output list
            # would then map past its end and hide the pass as an error.
            return FileUDFResult(outputs=outputs(given) if callable(outputs) else outputs), True

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
    def test_the_parent_of_several_rows_has_a_row(self, run, backend):
        run(_records("r0", "r1"), EXPANSION)

        assert "r0" in _by_id(backend)

    def test_the_parent_of_a_single_row_has_one_too(self, run, backend):
        """Every output row is minted on an expansion, not only the split ones, so
        the one-to-one parent loses its identity alongside the split one."""
        run(_records("r0", "r1"), EXPANSION)

        assert "r1" in _by_id(backend)

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
    row of it. Resolved through the rows' `producer_source_guid`, so the input is
    neither re-queued nor re-split and the rows it made stand."""

    def test_an_identical_rerun_does_not_invoke_the_tool(self, run):
        run(_records("r0", "r1"), EXPANSION)
        run(_records("r0", "r1"), EXPANSION)

        assert len(run.seen) == 1, f"the tool ran again on: {run.seen[1:]}"

    def test_the_children_keep_the_identities_they_were_given(self, run):
        first = run(_records("r0", "r1"), EXPANSION)
        second = run(_records("r0", "r1"), EXPANSION)

        assert [o["source_guid"] for o in second] == [o["source_guid"] for o in first]

    def test_it_holds_for_an_input_that_was_itself_expanded(self, run):
        """The case that rules out resolving this through `parent_source_guid`: an
        input produced by an upstream expansion passes its *own* ancestor to its
        children, never its own guid, so no row of the output names it there."""
        first = run(_records("m0", "m1", ancestor="s0"), EXPANSION)
        # The shape itself, asserted: the children name the grandparent, so no row
        # of the output names m0 or m1 and matching on this field cannot find them.
        assert {o.get("parent_source_guid") for o in first} == {"s0"}

        second = run(_records("m0", "m1", ancestor="s0"), EXPANSION)

        assert [o["source_guid"] for o in second] == [o["source_guid"] for o in first]


class TestWhatMustNotChangeWhileClosingThis:
    """A guard on the behaviour closing the gap above must leave alone. An attempt
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


class TestTheReasonAnAccountedInputCarries:
    def test_a_consumed_input_says_why_it_has_no_row_of_its_own(self, run, backend):
        """One reason for both directions. An expanded input is not collapsed, and
        the batch-length flag at the write site cannot tell one input's direction
        from another's, so the row says what is true of every such input: it was
        consumed and its content lives in rows keyed elsewhere."""
        run(_records("r0", "r1"), EXPANSION)

        rows = _by_id(backend)
        assert [rows["r0"]["disposition"], rows["r0"]["reason"]] == [
            "success",
            "consumed_into_output",
        ]
        assert [rows["r1"]["disposition"], rows["r1"]["reason"]] == [
            "success",
            "consumed_into_output",
        ]

    def test_the_minted_rows_carry_no_reason(self, run, backend):
        """A row that exists produced a record; only an input without one needs to
        say so. Asserting this stops the reason being written to every row."""
        output = run(_records("r0", "r1"), EXPANSION)
        minted = {o["source_guid"] for o in output}

        rows = _by_id(backend)
        assert minted and all(rows[guid]["reason"] is None for guid in minted)


class TestWhichInputARowNames:
    def test_a_minted_row_names_the_input_that_produced_it(self, run):
        output = run(_records("r0", "r1"), EXPANSION)

        assert [o.get("producer_source_guids") for o in output] == [["r0"], ["r0"], ["r1"]]

    def test_it_is_the_immediate_input_and_not_the_ancestor(self, run):
        """The whole reason the field exists. `parent_source_guid` degrades to the
        pool ancestor once an input has itself been expanded; the producer must
        not, or a chained expansion resolves to a record this action never saw."""
        output = run(_records("m0", "m1", ancestor="s0"), EXPANSION)

        assert [o.get("parent_source_guid") for o in output] == ["s0", "s0", "s0"]
        assert [o.get("producer_source_guids") for o in output] == [["m0"], ["m0"], ["m1"]]

    def test_a_row_the_tool_invented_names_no_producer(self, run):
        """A synthetic row maps to no input, so there is nothing to name. Writing
        one anyway would hand a real input's carry a row it did not make."""
        output = run(
            _records("r0", "r1"),
            [
                {"source_index": 0, "data": {"part": 1}},
                {"source_index": 0, "data": {"part": 2}},
                {"source_index": None, "data": {"part": "invented"}},
            ],
        )

        invented = [o for o in output if o["content"][ACTION].get("part") == "invented"]
        assert len(invented) == 1
        assert not invented[0].get("producer_source_guids")


class TestTheProducerSurvivesStorage:
    def test_a_third_run_still_carries_the_expansion(self, run):
        """The interaction the two halves meet in: the rows are written, read back
        for carry-forward, and written again. A producer that does not survive the
        round trip re-splits the input on the third run, not the second — so two
        runs would not catch it."""
        first = run(_records("r0", "r1"), EXPANSION)
        run(_records("r0", "r1"), EXPANSION)
        third = run(_records("r0", "r1"), EXPANSION)

        assert len(run.seen) == 1, f"the tool ran again on: {run.seen[1:]}"
        assert [o["source_guid"] for o in third] == [o["source_guid"] for o in first]


class TestTheSameGapReachedWithMatchingCounts:
    """r0 splits into two, r1 gives one, r2 is dropped: as many rows out as records
    in, so `is_expansion` is false and the input keeps its disposition row through
    the contributor sweep. The second half is shared — no row carries r0's identity
    either, so carry-forward could not resolve it and the input was re-split on
    every run, reordering a FILE-mode input that is mapped by position.
    """

    @staticmethod
    def _matched(given: list[str]) -> list[dict]:
        out: list[dict] = []
        for index, guid in enumerate(given):
            for part in range(2 if guid == "r0" else 1 if guid == "r1" else 0):
                out.append({"source_index": index, "data": {"part": part}})
        return out

    def test_the_split_input_is_not_re_invoked(self, run):
        run(_records("r0", "r1", "r2"), self._matched)
        run(_records("r0", "r1", "r2"), self._matched)

        assert run.seen[1] == ["r2"], f"re-invoked on: {run.seen[1]}"

    def test_its_rows_keep_the_identities_they_were_given(self, run):
        first = run(_records("r0", "r1", "r2"), self._matched)
        split = {o["source_guid"] for o in first if "r0" in (o.get("producer_source_guids") or [])}
        assert len(split) == 2, "the split rows are the ones minted an identity"

        second = run(_records("r0", "r1", "r2"), self._matched)

        assert split <= {o["source_guid"] for o in second}

    def test_the_disposition_rows_do_not_accumulate_across_runs(self, run, backend):
        """The target file is replaced whole, so counting its rows cannot fail. The
        rows that pile up are the dispositions: every re-split mints two more
        identities and writes a row for each, and the previous pair stays."""
        run(_records("r0", "r1", "r2"), self._matched)
        after_one = len(_rows(backend))

        run(_records("r0", "r1", "r2"), self._matched)
        run(_records("r0", "r1", "r2"), self._matched)

        assert len(_rows(backend)) == after_one

    def test_the_dropped_input_is_not_claimed_as_consumed(self, run, backend):
        """r2 produced nothing. Its row must stay the `unprocessed` tombstone —
        a sweep that credited every named input would add a success row beside it,
        and the UNIQUE key lets both rows coexist."""
        run(_records("r0", "r1", "r2"), self._matched)

        r2_rows = [r for r in _rows(backend) if r["record_id"] == "r2"]
        assert [r["disposition"] for r in r2_rows] == ["unprocessed"]


class TestARecordModeExpansion:
    """`online_llm` and the batch result strategy also set `is_expansion`, for one
    record whose output became several. The input gets its disposition row from the
    result level there, so only the second half is missing — no row carries its
    identity, so carry-forward re-queues and re-expands it on every run.
    """

    @staticmethod
    def _enriched(source_guid: str, count: int) -> list[dict]:
        context = ProcessingContext(agent_config={"kind": "llm"}, agent_name=ACTION)
        context.source_data = [{"source_guid": source_guid, "content": {}}]
        context.is_first_stage = False
        result = ProcessingResult.success(
            data=[
                {"source_guid": source_guid, "content": {ACTION: {"i": i}}} for i in range(count)
            ],
            source_guid=source_guid,
            is_expansion=True,
        )
        return LineageEnricher().enrich(result, context).data

    def test_every_minted_row_names_the_record_it_came_from(self):
        rows = self._enriched("r0", 3)

        assert [r.get("producer_source_guids") for r in rows] == [["r0"], ["r0"], ["r0"]]
        assert all(r["source_guid"] != "r0" for r in rows), "each row is minted its own"

    def test_the_record_resolves_through_them_for_carry_forward(self):
        rows = self._enriched("r0", 3)
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = rows

        found, missing = build_carry_forward({"r0"}, ACTION, "f.json", backend)

        assert [r["source_guid"] for r in found] == [r["source_guid"] for r in rows]
        assert missing == set()


class TestAnExpansionThatAlsoCollapses:
    """A tool may merge some inputs and split others in one call. If the totals come
    out higher it is an expansion, and every row is re-keyed — so a merged row has to
    name every input it consumed, not just the first. Naming one writes a terminal row
    for the others that nothing can resolve, and the next run reprocesses them beside
    the row already holding their content.
    """

    @staticmethod
    def _merge_and_split(given: list[str]) -> list[dict]:
        out: list[dict] = []
        merged = [i for i, g in enumerate(given) if g in ("r0", "r1")]
        if merged:
            out.append(
                {"source_index": merged, "data": {"group": "+".join(given[i] for i in merged)}}
            )
        for i, g in enumerate(given):
            if g == "r2":
                out += [{"source_index": i, "data": {"part": n}} for n in range(3)]
        return out

    def test_a_merged_row_names_every_input_it_consumed(self, run):
        output = run(_records("r0", "r1", "r2"), self._merge_and_split)
        merged = next(o for o in output if "group" in o["content"][ACTION])

        assert merged.get("producer_source_guids") == ["r0", "r1"]

    def test_the_output_does_not_grow_on_a_rerun(self, run):
        first = run(_records("r0", "r1", "r2"), self._merge_and_split)
        second = run(_records("r0", "r1", "r2"), self._merge_and_split)
        third = run(_records("r0", "r1", "r2"), self._merge_and_split)

        assert [len(first), len(second), len(third)] == [4, 4, 4]

    def test_no_input_is_reprocessed(self, run):
        run(_records("r0", "r1", "r2"), self._merge_and_split)
        run(_records("r0", "r1", "r2"), self._merge_and_split)

        assert len(run.seen) == 1, f"the tool ran again on: {run.seen[1:]}"

    def test_the_merged_inputs_content_appears_once(self, run):
        """The harm, stated as data rather than as invocations: r1 was folded into a
        row with r0, so a second row built from r1 alone is its content twice."""
        run(_records("r0", "r1", "r2"), self._merge_and_split)
        output = run(_records("r0", "r1", "r2"), self._merge_and_split)

        groups = sorted(
            o["content"][ACTION]["group"] for o in output if "group" in o["content"][ACTION]
        )
        assert groups == ["r0+r1"]


class TestAPlainCollapseIsAlsoResolvable:
    """The same defect without an expansion: a many-to-one output carries only its
    first contributor's guid, so the rest get a terminal row nothing names. Their
    content is then rebuilt beside the row already holding it.
    """

    @staticmethod
    def _merge_all(given: list[str]) -> list[dict]:
        return [{"source_index": list(range(len(given))), "data": {"merged": "+".join(given)}}]

    def test_the_carrier_names_the_contributors_it_does_not_carry(self, run):
        """Only the ones it does not carry: the row's own guid already accounts for the
        first contributor, so listing it again would put a redundant entry on every
        ordinary 1:1 row too."""
        output = run(_records("r0", "r1"), self._merge_all)

        assert output[0]["source_guid"] == "r0"
        assert output[0].get("producer_source_guids") == ["r1"]

    def test_a_contributor_is_not_reprocessed(self, run):
        run(_records("r0", "r1"), self._merge_all)
        run(_records("r0", "r1"), self._merge_all)

        assert len(run.seen) == 1, f"the tool ran again on: {run.seen[1:]}"

    def test_the_output_does_not_grow(self, run):
        first = run(_records("r0", "r1"), self._merge_all)
        third = (
            run(_records("r0", "r1"), self._merge_all),
            run(_records("r0", "r1"), self._merge_all),
        )[1]

        assert [len(first), len(third)] == [1, 1]


class TestAProducerIsAlwaysARealInput:
    def test_a_row_whose_input_carries_no_identity_names_no_producer(self, run):
        """An input with no source_guid leaves the row nothing real to name. Writing
        the intermediate guid this action minted a step earlier would hand a consumer
        an identity no input holds."""
        records = [
            {"content": {"prev": {"id": "x"}}},
            {"source_guid": "r1", "content": {"prev": {"id": "r1"}}},
        ]
        output = run(records, EXPANSION)

        for row in output:
            for guid in row.get("producer_source_guids") or []:
                assert guid in {"r1"}, f"{guid} names no input of this action"
