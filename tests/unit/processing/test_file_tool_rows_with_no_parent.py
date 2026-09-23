"""Identity of a row a FILE tool emitted with no input to inherit from.

``_reattach_source_guid`` mints in two places. One is several rows claiming a
single parent (615); the other is a row with nothing to inherit — synthetic
(``source_index: None``), or mapped to a parent that carries no identity of its
own. Both mint, so both take on everything a minted identity implies; this file
pins the second against the first.
"""

import json
import pathlib
import tempfile

from agent_actions.processing.source_resolution import resolve_source_content
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.utils.udf_management.registry import FileUDFResult
from agent_actions.workflow.merge import merge_records_by_key
from agent_actions.workflow.pipeline_file_mode import reconcile_outputs

UPSTREAM = {"source": {"t": "alpha"}, "a1": {"v": 1}}

MARKS = ("_delta_mode", "version_correlation_id", "parent_source_guid")


def records(*guids, content=None):
    return [
        {
            "source_guid": g,
            "version_correlation_id": f"V{i}",
            "content": dict(content) if content else {"prev": {"id": i}},
        }
        for i, g in enumerate(guids)
    ]


def invented(count):
    """*count* rows that name no input, which is what `source_index: None` says."""
    return FileUDFResult([{"source_index": None, "data": {"o": i}} for i in range(count)])


def stored(rows):
    """A row as target storage holds it, so it survives lifecycle validation."""
    return [{**r, "_state": "processed", "_schema_version": 1} for r in rows]


def marks(row):
    return {k: row.get(k) for k in MARKS}


class TestARowWithNoParentIsStillWholeWhenReadBack:
    """A minted guid joins nothing upstream, so the row has to be stored whole
    rather than as a delta the reader cannot rejoin."""

    def test_it_keeps_the_namespaces_the_file_carried(self):
        rows, _ = reconcile_outputs(invented(2), "a2", records("G0", "G1", content=UPSTREAM))

        with tempfile.TemporaryDirectory() as directory:
            backend = SQLiteBackend(str(pathlib.Path(directory) / "s.db"), "wf")
            backend.initialize()
            backend.save_metadata("execution_order", json.dumps(["a1", "a2"]))
            backend.save_metadata("dependency_graph", json.dumps({"a1": [], "a2": ["a1"]}))
            backend.write_target(
                "a1",
                "f.json",
                stored([{"source_guid": g, "content": dict(UPSTREAM)} for g in ("G0", "G1")]),
            )
            backend.write_target("a2", "f.json", stored(rows))

            read_back = backend.read_target("a2", "f.json")

        assert [sorted(r.get("content", {})) for r in read_back] == [
            ["a1", "a2", "source"],
            ["a1", "a2", "source"],
        ]


class TestRowsWithNoParentAreNotFannedBackIn:
    def test_a_merge_keeps_them_apart(self):
        """They inherit the correlation id of the record standing in for their
        namespaces, and a merge groups on that before anything else — collapsing
        rows that were just given distinct identities."""
        rows, _ = reconcile_outputs(invented(2), "a2", records("G0", "G1"))

        assert len(merge_records_by_key(rows)) == 2

    def test_one_beside_an_ordinary_row_does_not_swallow_it(self):
        """The mixed batch: a synthetic row and a row that inherited its parent.
        They share nothing, and a merge must leave both standing."""
        raw = FileUDFResult(
            [{"source_index": None, "data": {"o": 0}}, {"source_index": 0, "data": {"o": 1}}]
        )
        rows, _ = reconcile_outputs(raw, "a2", records("G0", "G1"))

        assert len(merge_records_by_key(rows)) == 2


class TestARowWithNoParentSaysHowToResolveIt:
    """``parent_source_guid`` means "my own guid matches nothing in the pool".
    A minted one never does, so the row has to name an identity that does."""

    def test_it_names_the_identity_of_the_input_whose_namespaces_it_carries(self):
        rows, _ = reconcile_outputs(invented(2), "a2", records("G0", "G1"))

        assert [r.get("parent_source_guid") for r in rows] == ["G0", "G0"]

    def test_the_source_pool_resolves_through_it(self):
        rows, _ = reconcile_outputs(invented(1), "a2", records("G0", "G1"))
        pool = [{"source_guid": "G0", "content": {"source": {"t": "alpha"}}}]

        resolved = resolve_source_content(rows[0], rows[0].get("source_guid"), pool)

        assert resolved == pool[0]

    def test_an_ancestor_the_input_already_carries_wins_over_the_input_itself(self):
        """The input may itself be an expansion child, whose minted guid matches
        nothing in the pool either. Pass on the pool-resolvable one."""
        parents = [{"source_guid": "M0", "parent_source_guid": "POOL0", "content": {}}]
        rows, _ = reconcile_outputs(invented(1), "a2", parents)

        assert rows[0]["parent_source_guid"] == "POOL0"


class TestTheTwoMintingBranchesAgree:
    def test_a_row_with_no_parent_is_marked_like_a_row_that_shares_one(self):
        """Both are born here, so both take on what a minted identity implies.
        A difference between them would have to be one this asserts away."""
        shared = FileUDFResult(
            [{"source_index": 0, "data": {"o": 0}}, {"source_index": 0, "data": {"o": 1}}]
        )
        sharing, _ = reconcile_outputs(shared, "a2", records("G0", "G1"))
        parentless, _ = reconcile_outputs(invented(2), "a2", records("G0", "G1"))

        assert [marks(r) for r in parentless] == [marks(r) for r in sharing]


class TestAParentThatCarriesNoIdentity:
    """Mapped to a real input that has no guid of its own: the row is named, its
    parent is not. It is minted like any other row that cannot inherit."""

    def test_it_is_marked_as_minted(self):
        rows, _ = reconcile_outputs(
            FileUDFResult([{"source_index": 1, "data": {"o": 0}}]),
            "a2",
            [{"source_guid": "G0", "content": {}}, {"content": {}}],
        )

        assert rows[0]["_delta_mode"] == "full"
        assert "version_correlation_id" not in rows[0]

    def test_it_is_attributed_to_its_own_parent_not_to_the_first_input(self):
        """The stand-in only applies to a row that names no parent. This one
        does, and borrowing a different record's identity would misattribute it."""
        rows, _ = reconcile_outputs(
            FileUDFResult([{"source_index": 1, "data": {"o": 0}}]),
            "a2",
            [{"source_guid": "G0", "content": {}}, {"parent_source_guid": "POOL1", "content": {}}],
        )

        assert rows[0]["parent_source_guid"] == "POOL1"

    def test_a_parent_with_no_identity_at_all_is_not_given_one(self):
        rows, _ = reconcile_outputs(
            FileUDFResult([{"source_index": 1, "data": {"o": 0}}]),
            "a2",
            [{"source_guid": "G0", "content": {}}, {"content": {}}],
        )

        assert "parent_source_guid" not in rows[0]


class TestWhenThereIsNoInputToStandIn:
    def test_the_row_is_still_marked_as_minted(self):
        rows, _ = reconcile_outputs(invented(1), "a2", [])

        assert rows[0]["_delta_mode"] == "full"

    def test_no_attribution_is_invented_for_it(self):
        rows, _ = reconcile_outputs(invented(1), "a2", [])

        assert "parent_source_guid" not in rows[0]


class TestWhatIsNotMinted:
    """The marks belong to minting. A row that inherited an identity keeps the
    correlation id and the delta storage that identity already joins."""

    def test_a_one_to_one_row_is_untouched(self):
        raw = FileUDFResult([{"source_index": 0, "data": {"o": 0}}])
        rows, _ = reconcile_outputs(raw, "a2", records("G0", "G1"))

        assert rows[0]["source_guid"] == "G0"
        assert rows[0]["version_correlation_id"] == "V0"
        assert "_delta_mode" not in rows[0]

    def test_a_collapse_still_inherits_its_first_contributor(self):
        raw = FileUDFResult([{"source_index": [0, 1], "data": {"o": 0}}])
        rows, _ = reconcile_outputs(raw, "a2", records("G0", "G1"))

        assert rows[0]["source_guid"] == "G0"
        assert "_delta_mode" not in rows[0]

    def test_a_row_with_no_parent_does_not_take_the_identity_it_is_attributed_to(self):
        """The stand-in answers "resolve me through this", not "I am this". Taking
        the guid would put two rows under one identity, which is 615 again."""
        rows, _ = reconcile_outputs(invented(1), "a2", records("G0"))

        assert rows[0]["source_guid"] != "G0"
        assert rows[0]["parent_source_guid"] == "G0"
