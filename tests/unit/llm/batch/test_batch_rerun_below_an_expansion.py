"""A batch re-run of an expansion whose own input is an expansion child.

``producer_source_guids`` names the immediate inputs a row consumed. Where the
upstream action is itself an expansion those inputs are its minted children, and
they are minted again every run. The stored rows then name producers that no
longer exist, this run's rows name the current ones, the two sets never
intersect, and nothing marks the stored generation as replaced.

What tells the two apart is what this action took as input: a producer named by
none of it is a generation that is gone, while a producer still standing in the
input is one this run did not answer for. That set is *not* the batch context
map — the disposition gate narrows the input before the map is built, so the map
holds only what was submitted and a rule reading it alone deletes the rows of
every input the gate carried. It has to be the input as it stood before
narrowing, recorded at submission and read back here.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.config.types import RunMode
from agent_actions.llm.batch.core.batch_models import BatchIdentity, RecoveryContext
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.batch.services.processing_recovery import finalize_batch_output
from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.processing.types import ProcessingContext, ProcessingResult, ProcessingStatus
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "expand_question"
RELATIVE = "page.json"
STAGED = "S"

# Spelled here rather than imported so this test pins the convention from the
# outside: production owning both ends of a key it alone reads would let the two
# drift together and still pass.
INPUTS_KEY = f"batch_inputs:{ACTION}:{RELATIVE}"


def _row(guid: str, *, producers: list[str], ancestor: str = STAGED) -> dict[str, Any]:
    """A row of the lower expansion: minted, naming the upstream child it consumed."""
    return {
        "source_guid": guid,
        "parent_source_guid": ancestor,
        "producer_source_guids": producers,
        "answer": f"answer-for-{guid}",
        "_delta_mode": "full",
        "_state": "processed",
    }


def _input(guid: str, ancestor: str = STAGED) -> dict[str, Any]:
    """An upstream expansion child, as it stands in this action's input."""
    return {"source_guid": guid, "parent_source_guid": ancestor, "page_content": "text"}


def _finalize(
    tmp_path: Path,
    stored: list[dict],
    produced: list[dict],
    submitted: list[str],
    run_inputs: list[str] | None,
) -> list[dict]:
    """Finalize a run over *stored*, having submitted *submitted* out of *run_inputs*.

    *run_inputs* is the input as it stood before the disposition gate narrowed it;
    None means the run recorded none, which is the case that must not infer
    anything. Returns the rows the write landed, read back out of the store.
    """
    backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    backend.initialize()
    backend._write_target_raw(ACTION, RELATIVE, stored)
    backend._reconstruction_cache.clear()
    if run_inputs is not None:
        backend.save_metadata(INPUTS_KEY, json.dumps(sorted(run_inputs)))

    service = BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=MagicMock(),
        workflow_name=ACTION,
        storage_backend=backend,
    )
    # The conversion is not what is under test: it is the step that hands the
    # merge this run's rows, and the rows it hands over are built above.
    service._convert_batch_results_to_workflow_format = MagicMock(  # type: ignore[method-assign]
        return_value=(list(produced), MagicMock(), None)
    )

    output_directory = str(tmp_path / "out")
    Path(output_directory).mkdir(parents=True, exist_ok=True)
    context = RecoveryContext(
        service=service,
        manager=MagicMock(),
        provider=MagicMock(),
        agent_config={"kind": "llm"},
        output_directory=output_directory,
        action_name=ACTION,
        start_time=0.0,
    )
    identity = BatchIdentity(batch_id="batch-1", file_name=RELATIVE, entry=MagicMock())

    # Only what was submitted reaches the context map: the gate narrows first.
    context_map = {f"t{index}": _input(guid) for index, guid in enumerate(submitted)}

    finalize_batch_output(context, identity, batch_results=[], context_map=context_map)

    backend._reconstruction_cache.clear()
    return backend.read_target_for_rewrite(ACTION, RELATIVE)


def _guids(rows: list[dict]) -> list[str]:
    return [row["source_guid"] for row in rows]


class TestAnExpansionBelowAnExpansion:
    def test_a_rerun_with_nothing_changed_stays_at_four_rows(self, tmp_path):
        """The defect: run 2's rows are written beside run 1's, and the file doubles."""
        stored = [
            _row("b1", producers=["a1"]),
            _row("b2", producers=["a1"]),
            _row("b3", producers=["a2"]),
            _row("b4", producers=["a2"]),
        ]
        produced = [
            _row("b5", producers=["a3"]),
            _row("b6", producers=["a3"]),
            _row("b7", producers=["a4"]),
            _row("b8", producers=["a4"]),
        ]

        result = _finalize(
            tmp_path, stored, produced, submitted=["a3", "a4"], run_inputs=["a3", "a4"]
        )

        assert _guids(result) == ["b5", "b6", "b7", "b8"], (
            f"the previous generation was carried beside its replacement: {_guids(result)}"
        )

    def test_rows_left_out_are_reported_once_per_write(self, tmp_path, caplog):
        """One decision, one record: the merge decides once, and nothing else reports it."""
        stored = [
            _row("b1", producers=["a1"]),
            _row("b2", producers=["a1"]),
            _row("b3", producers=["a2"]),
            _row("b4", producers=["a2"]),
        ]
        produced = [_row("b5", producers=["a3"]), _row("b6", producers=["a4"])]

        with caplog.at_level(logging.DEBUG):
            _finalize(tmp_path, stored, produced, submitted=["a3", "a4"], run_inputs=["a3", "a4"])

        left = [r for r in caplog.records if "not carried forward" in r.getMessage().lower()]
        assert len(left) == 1, [(r.name, r.levelname, r.getMessage()) for r in left]
        assert left[0].name == "agent_actions.processing.disposition_gate"
        assert left[0].levelno == logging.INFO
        assert left[0].getMessage().startswith("4 stored row(s) not carried"), left[0].getMessage()

    def test_an_input_this_run_did_not_answer_for_keeps_its_rows(self, tmp_path):
        """A producer still standing in the input is not a generation that is gone."""
        stored = [
            _row("b1", producers=["a1"]),
            _row("b2", producers=["a1"]),
            _row("b3", producers=["a2"]),
        ]
        # a2 was submitted and filtered out, so it produced nothing this run.
        produced = [_row("b5", producers=["a1"]), _row("b6", producers=["a1"])]

        result = _finalize(
            tmp_path, stored, produced, submitted=["a1", "a2"], run_inputs=["a1", "a2"]
        )

        assert _guids(result) == ["b5", "b6", "b3"], (
            f"a row whose producer is still an input was dropped: {_guids(result)}"
        )

    def test_a_gate_carried_input_keeps_its_rows(self, tmp_path):
        """The input the disposition gate carried is still an input.

        It never reaches the context map — the gate narrows before the map is
        built — so a rule reading the map alone reads it as a generation that is
        gone and deletes its rows. That is every ordinary incremental run.
        """
        stored = [
            _row("b1", producers=["a1"]),
            _row("b2", producers=["a1"]),
            _row("b3", producers=["a2"]),
        ]
        produced = [_row("b5", producers=["a2"])]

        result = _finalize(tmp_path, stored, produced, submitted=["a2"], run_inputs=["a1", "a2"])

        assert _guids(result) == ["b5", "b1", "b2"], (
            f"the rows of an input the gate carried were deleted: {_guids(result)}"
        )

    def test_an_unrecorded_input_set_carries_rather_than_deletes(self, tmp_path):
        """With nothing recorded about the input, nothing is inferred away.

        The inference deletes rows, so the case where it cannot be made must fail
        towards keeping them — a batch submitted before the input was recorded
        would otherwise erase every stored row it could not attribute.
        """
        stored = [_row("b1", producers=["a1"]), _row("b2", producers=["a2"])]
        produced = [_row("b5", producers=["a3"])]

        result = _finalize(tmp_path, stored, produced, submitted=["a3"], run_inputs=None)

        assert _guids(result) == ["b5", "b1", "b2"], (
            f"rows were deleted on an input set that says nothing: {_guids(result)}"
        )


class TestTheRowShapesTheseTestsRelyOn:
    """Nested expansion really does produce the fields the rule above reads."""

    @pytest.mark.parametrize("run", ["first", "second"])
    def test_a_child_of_an_expansion_names_its_producer_and_keeps_its_ancestor(self, run):
        """B's rows name A's child as producer and keep the staged record as ancestor."""
        upstream_child = f"a-{run}"
        context = ProcessingContext(
            agent_config={"kind": "llm"}, agent_name=ACTION, mode=RunMode.BATCH
        )
        # A's child as it stands in B's input: re-keyed by A's expansion, with the
        # staged record preserved as its ancestor.
        context.source_data = [_input(upstream_child)]

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=[
                {"source_guid": upstream_child, "parent_source_guid": STAGED, "answer": "a"},
                {"source_guid": upstream_child, "parent_source_guid": STAGED, "answer": "b"},
            ],
            source_guid=upstream_child,
        )
        result.is_expansion = True

        rows = EnrichmentPipeline().enrich(result, context).data

        assert [r.get("producer_source_guids") for r in rows] == [[upstream_child]] * 2
        assert [r.get("parent_source_guid") for r in rows] == [STAGED] * 2, (
            "the pool ancestor was overwritten with the intermediate child"
        )
        minted = [r["source_guid"] for r in rows]
        assert upstream_child not in minted
        assert len(set(minted)) == 2
