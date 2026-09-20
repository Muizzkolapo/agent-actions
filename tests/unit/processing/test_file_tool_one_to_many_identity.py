"""Identity of rows a FILE tool produced several of from one input."""

import json
import pathlib
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.processing.disposition_gate import build_carry_forward
from agent_actions.processing.strategies.file_tool import FileToolStrategy
from agent_actions.processing.types import ProcessingContext, ProcessingStatus
from agent_actions.record.reasons import TOOL_MISSING_RECORD
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.utils.udf_management.registry import FileUDFResult
from agent_actions.workflow.merge import merge_records_by_key
from agent_actions.workflow.pipeline_file_mode import reconcile_outputs


def records(*guids):
    return [{"source_guid": g, "content": {"prev": {"id": i}}} for i, g in enumerate(guids)]


def outputs(*pairs):
    return FileUDFResult([{"source_index": i, "data": {"out": v}} for i, v in pairs])


def stored(rows):
    """A row as target storage holds it, so it survives lifecycle validation."""
    return [{**r, "_state": "processed", "_schema_version": 1} for r in rows]


def invoke(records_in, raw):
    context = ProcessingContext(
        agent_config={"kind": "tool", "granularity": "file"}, agent_name="split_tool"
    )
    context.source_data = records_in
    with patch(
        "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
        return_value=(raw, True),
    ):
        return FileToolStrategy().invoke(records_in, context)


# Two outputs from input 0, one from input 1, and input 2 dropped. The counts
# match, so a rule comparing lengths sees no expansion.
SPLIT = ((0, "alpha-1"), (0, "alpha-2"), (1, "beta"))

UPSTREAM = {"source": {"t": "alpha"}, "a1": {"v": 1}}


class TestSeveralOutputsFromOneInput:
    def test_each_gets_its_own_identity(self):
        rows, _ = reconcile_outputs(outputs(*SPLIT), "split_tool", records("G0", "G1", "G2"))
        guids = [r["source_guid"] for r in rows]

        assert len(set(guids)) == 3

    def test_each_keeps_the_parent_it_came_from(self):
        """Only the re-minted rows carry one. The lone child still *is* its
        parent's row, so naming itself as its own parent would be noise."""
        rows, _ = reconcile_outputs(outputs(*SPLIT), "split_tool", records("G0", "G1", "G2"))

        assert [r.get("parent_source_guid") for r in rows] == ["G0", "G0", None]

    def test_a_row_that_is_the_only_child_is_not_re_minted(self):
        """Nothing is ambiguous about a lone child, and re-minting it would
        change the identity of every ordinary one-to-one row."""
        rows, _ = reconcile_outputs(outputs(*SPLIT), "split_tool", records("G0", "G1", "G2"))

        assert rows[2]["source_guid"] == "G1"


class TestTheRowsSurviveBeingStored:
    def test_carry_forward_returns_every_row_it_is_asked_for(self):
        """Asked for the stored rows' own identities, which is the shape a
        repair passes. A retry asks with the *input* identities instead, and
        the parent is legitimately absent from them — it is re-queued, loudly.
        """
        rows, _ = reconcile_outputs(outputs(*SPLIT), "split_tool", records("G0", "G1", "G2"))
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = rows

        found, missing = build_carry_forward(
            {r["source_guid"] for r in rows}, "split_tool", "f.json", backend
        )

        assert len(found) == 3
        assert missing == set()

    def test_a_checkpoint_round_trip_returns_every_row(self):
        """The checkpoint table is unique per identity, so two rows sharing one
        overwrite each other on the way in rather than on the way out."""
        rows, _ = reconcile_outputs(outputs(*SPLIT), "split_tool", records("G0", "G1", "G2"))
        with tempfile.TemporaryDirectory() as directory:
            backend = SQLiteBackend(str(pathlib.Path(directory) / "s.db"), "wf")
            backend.initialize()
            backend.save_checkpoint_records("split_tool", "f.json", stored(rows))

            assert len(backend.read_checkpoint_records("split_tool", "f.json")) == 3


class TestAMintedRowIsStillWholeWhenReadBack:
    """A minted guid joins nothing upstream, so the row has to be stored whole
    rather than as a delta the reader cannot rejoin."""

    def test_it_keeps_the_namespaces_its_parent_carried(self):
        rows, _ = reconcile_outputs(
            outputs(*SPLIT),
            "a2",
            [{"source_guid": g, "content": dict(UPSTREAM)} for g in ("G0", "G1", "G2")],
        )

        with tempfile.TemporaryDirectory() as directory:
            backend = SQLiteBackend(str(pathlib.Path(directory) / "s.db"), "wf")
            backend.initialize()
            backend.save_metadata("execution_order", json.dumps(["a1", "a2"]))
            backend.save_metadata("dependency_graph", json.dumps({"a1": [], "a2": ["a1"]}))
            backend.write_target(
                "a1",
                "f.json",
                [
                    {
                        "source_guid": "G0",
                        "_state": "processed",
                        "_schema_version": 1,
                        "content": dict(UPSTREAM),
                    }
                ],
            )
            backend.write_target("a2", "f.json", stored(rows))

            read_back = backend.read_target("a2", "f.json")

        assert [sorted(r.get("content", {})) for r in read_back[:2]] == [
            ["a1", "a2", "source"],
            ["a1", "a2", "source"],
        ]


class TestAMintedRowIsNotFannedBackIn:
    def test_a_merge_keeps_them_apart(self):
        """They share the parent's correlation id until it is dropped, and a
        merge groups on that before anything else — collapsing the rows the
        identity was just minted to separate."""
        parents = [
            {"source_guid": "G0", "version_correlation_id": "V0"},
            {"source_guid": "G1", "version_correlation_id": "V1"},
        ]
        rows, _ = reconcile_outputs(outputs(*SPLIT), "t", parents)

        assert len(merge_records_by_key(rows)) == 3


class TestWhatTheStrategyStillReports:
    def test_the_dropped_input_is_still_tombstoned(self):
        """Input 2 produced nothing. Treating the split as an expansion would
        skip the check that notices, trading one silent loss for another."""
        results = invoke(records("G0", "G1", "G2"), outputs(*SPLIT))

        unprocessed = [r for r in results if r.status == ProcessingStatus.UNPROCESSED]
        assert [r.source_guid for r in unprocessed] == ["G2"]
        assert unprocessed[0].skip_reason == TOOL_MISSING_RECORD

    def test_the_produced_rows_come_back_intact(self):
        results = invoke(records("G0", "G1", "G2"), outputs(*SPLIT))
        success = [r for r in results if r.status == ProcessingStatus.SUCCESS][0]

        assert len(success.data) == 3
        assert len({item["source_guid"] for item in success.data}) == 3


class TestMappingsThatAreNotOneToMany:
    def test_a_one_to_one_mapping_inherits_its_parent(self):
        rows, _ = reconcile_outputs(outputs((0, "a"), (1, "b")), "t", records("G0", "G1"))

        assert [r["source_guid"] for r in rows] == ["G0", "G1"]

    @pytest.mark.parametrize("guids", [("G0", "G1"), ("G0", "G1", "G2")])
    def test_many_inputs_to_one_output_inherit_the_first(self, guids):
        """A collapse is the other direction and keeps the existing answer."""
        raw = FileUDFResult([{"source_index": list(range(len(guids))), "data": {"out": "merged"}}])

        rows, _ = reconcile_outputs(raw, "t", records(*guids))

        assert [r["source_guid"] for r in rows] == ["G0"]
