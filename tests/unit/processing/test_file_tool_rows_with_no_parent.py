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
from unittest.mock import MagicMock

import pytest

from agent_actions.processing.enrichment import LineageEnricher, VersionIdEnricher
from agent_actions.processing.source_resolution import resolve_source_content
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.utils.udf_management.registry import FileUDFResult
from agent_actions.workflow.merge import _select_universal_key, merge_records_by_key
from agent_actions.workflow.pipeline_file_mode import reconcile_outputs

UPSTREAM = {"source": {"t": "alpha"}, "a1": {"v": 1}}

# The marks that follow from minting. Attribution is not among them: it follows
# from whether the row named a parent, which is what the two branches differ on.
STORAGE_MARKS = ("_delta_mode", "version_correlation_id")


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


def storage_marks(row):
    return {k: row.get(k) for k in STORAGE_MARKS}


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

    def test_its_source_resolves_once_it_comes_back_whole(self):
        """What an attribution would have bought, bought by the storage mark
        instead: the row carries `source` in its own content, which is the first
        thing `resolve_source_content` reads. Stored as a delta it came back
        without it, and the lookup fell through to a guid the pool never had."""
        rows, _ = reconcile_outputs(invented(1), "a2", records("G0", content=UPSTREAM))

        with tempfile.TemporaryDirectory() as directory:
            backend = SQLiteBackend(str(pathlib.Path(directory) / "s.db"), "wf")
            backend.initialize()
            backend.save_metadata("execution_order", json.dumps(["a1", "a2"]))
            backend.save_metadata("dependency_graph", json.dumps({"a1": [], "a2": ["a1"]}))
            backend.write_target(
                "a1", "f.json", stored([{"source_guid": "G0", "content": dict(UPSTREAM)}])
            )
            backend.write_target("a2", "f.json", stored(rows))
            read_back = backend.read_target("a2", "f.json")[0]

        pool = [{"source_guid": "G0", "content": {"source": dict(UPSTREAM["source"])}}]
        resolved = resolve_source_content(read_back, read_back.get("source_guid"), pool)

        assert resolved is not None
        assert resolved["content"]["source"] == UPSTREAM["source"]


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


class TestARowThatNamesNoParent:
    """``parent_source_guid`` is read as the row's *producer* — by source lookup,
    and by the gate that decides which stored rows a repair may replace. A
    synthetic row has no single producer, so it claims none."""

    @pytest.mark.parametrize("version_merge", [False, True])
    def test_it_claims_no_producer(self, version_merge):
        rows, _ = reconcile_outputs(
            invented(2), "a2", records("G0", "G1"), version_merge=version_merge
        )

        assert [row.get("parent_source_guid") for row in rows] == [None, None]

    @pytest.mark.parametrize("version_merge", [False, True])
    def test_an_ancestor_carried_from_the_input_is_cleared_not_kept(self, version_merge):
        """The row takes its namespaces from ``original_data[0]``, and the envelope
        carries that record's tracking fields with them. When the input is itself
        an expansion child it carries an ancestor, which arrives on the row looking
        inherited — every consumer would read it as this row's producer."""
        expansion_children = [
            {
                "source_guid": f"M{i}",
                "parent_source_guid": "POOL0",
                "content": {"a1": {"i": i}},
            }
            for i in range(2)
        ]

        rows, _ = reconcile_outputs(
            invented(2), "a2", expansion_children, version_merge=version_merge
        )

        assert [row.get("parent_source_guid") for row in rows] == [None, None]

    def test_it_does_not_take_the_identity_of_the_input_standing_in_for_it(self):
        """``_resolve_input_record`` stands ``original_data[0]`` in for namespace
        carry-forward. That is a content decision, not an identity one."""
        rows, _ = reconcile_outputs(invented(1), "a2", records("G0"))

        assert rows[0]["source_guid"] != "G0"


class TestARowThatNamesAParent:
    """It hands on the parent's pool-resolvable identity: a parent that is itself
    an expansion child has a minted guid matching nothing in the pool."""

    SHARED = FileUDFResult(
        [{"source_index": 0, "data": {"o": 0}}, {"source_index": 0, "data": {"o": 1}}]
    )

    @pytest.mark.parametrize("version_merge", [False, True])
    def test_an_ancestor_the_parent_carries_wins_over_the_parent_itself(self, version_merge):
        """Parametrised over the version-merge fork because that is the only mode
        in which this line is observable: with it off, ``RecordEnvelope.build``
        has already carried the ancestor onto the row and the branch never runs,
        so a version-merge action is the one place the precedence can be lost."""
        parents = [{"source_guid": "M0", "parent_source_guid": "POOL0", "content": {"a1": {}}}]

        rows, _ = reconcile_outputs(self.SHARED, "a2", parents, version_merge=version_merge)

        assert [row.get("parent_source_guid") for row in rows] == ["POOL0", "POOL0"]

    @pytest.mark.parametrize("version_merge", [False, True])
    def test_a_parent_with_no_ancestor_hands_on_its_own_identity(self, version_merge):
        parents = [{"source_guid": "G0", "content": {"a1": {}}}]

        rows, _ = reconcile_outputs(self.SHARED, "a2", parents, version_merge=version_merge)

        assert [row.get("parent_source_guid") for row in rows] == ["G0", "G0"]


class TestTheTwoMintingBranches:
    """Both are born here, so both take on what a minted identity implies for
    storage. They part on attribution, and only there."""

    SHARED = FileUDFResult(
        [{"source_index": 0, "data": {"o": 0}}, {"source_index": 0, "data": {"o": 1}}]
    )

    def test_they_carry_the_same_storage_marks(self):
        sharing, _ = reconcile_outputs(self.SHARED, "a2", records("G0", "G1"))
        parentless, _ = reconcile_outputs(invented(2), "a2", records("G0", "G1"))

        assert [storage_marks(r) for r in parentless] == [storage_marks(r) for r in sharing]

    def test_only_the_one_that_named_a_parent_claims_a_producer(self):
        """The stated difference. A row that shares a parent has one to name; a
        row that named none would have to borrow, and the field is read as a
        producer by the gate deciding which rows a repair may replace."""
        sharing, _ = reconcile_outputs(self.SHARED, "a2", records("G0", "G1"))
        parentless, _ = reconcile_outputs(invented(2), "a2", records("G0", "G1"))

        assert [r.get("parent_source_guid") for r in sharing] == ["G0", "G0"]
        assert [r.get("parent_source_guid") for r in parentless] == [None, None]


class TestAParentThatCarriesNoIdentity:
    """Mapped to a real input that has no guid of its own: the row is named, its
    parent is not. It is minted like any other row that cannot inherit."""

    def test_it_is_marked_as_minted(self):
        rows, _ = reconcile_outputs(
            FileUDFResult([{"source_index": 1, "data": {"o": 0}}]),
            "a2",
            [
                {"source_guid": "G0", "content": {}},
                {"version_correlation_id": "V1", "content": {}},
            ],
        )

        assert rows[0]["_delta_mode"] == "full"
        assert rows[0]["version_correlation_id"] == "V1#0"

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


class TestUnderAVersionedAction:
    """``VersionIdEnricher`` assigns an id only to a row that has none, so the drop
    above is the only thing that can separate two rows born from one stand-in."""

    CONFIG = {
        "agent_type": "consumer",
        "is_versioned_agent": True,
        "version_base_name": "a2",
        "workflow_session_id": "sess",
        "action_name": "a2",
    }

    def _enriched(self, rows):
        context = ProcessingContext(
            agent_config=dict(self.CONFIG), agent_name="a2", is_first_stage=False
        )
        context.record_index = 0
        result = ProcessingResult.success(data=rows, source_guid=None)
        return VersionIdEnricher().enrich(result, context).data

    def test_two_rows_with_no_parent_end_with_distinct_ids(self):
        rows, _ = reconcile_outputs(invented(2), "a2", records("G0", "G1"))

        ids = [row.get("version_correlation_id") for row in self._enriched(rows)]

        assert len(set(ids)) == 2

    def test_an_id_that_reached_the_enricher_would_have_survived_it(self):
        """Why the drop cannot be left to the enricher. Built as the rows arrived
        before the drop, since the point is what the enricher does with them."""
        kept = [
            {"source_guid": "minted-1", "version_correlation_id": "V0", "content": {}},
            {"source_guid": "minted-2", "version_correlation_id": "V0", "content": {}},
        ]

        assert len(merge_records_by_key(self._enriched(kept))) == 1


class TestWhatTheDerivedCorrelationIdBuys:
    """The id is derived from the one the row inherited rather than dropped. A
    dropped id makes the row keyless, and ``_select_universal_key`` answers a
    mixed pool by keying every record on ``source_guid`` — which splits an
    unrelated fan-in that merely shares the merge pool."""

    FANNED = [
        {"source_guid": "m1", "version_correlation_id": "V9", "content": {"a": 1}},
        {"source_guid": "m2", "version_correlation_id": "V9", "content": {"b": 2}},
    ]

    def test_a_fan_in_sharing_the_pool_still_merges(self):
        rows, _ = reconcile_outputs(invented(1), "a2", records("G0"))

        pool = [dict(r) for r in self.FANNED] + rows

        assert _select_universal_key(pool) == "version_correlation_id"
        assert len(merge_records_by_key(pool)) == 2

    def test_the_matching_rows_of_two_version_branches_still_correlate(self):
        """Two branches of a versioned action run the same tool over the same
        input. A freshly minted id differs per branch and would leave the
        branches uncorrelated; a derived one matches."""
        parents = records("G0", "G1")

        first, _ = reconcile_outputs(invented(2), "a2", parents)
        second, _ = reconcile_outputs(invented(2), "a2", parents)

        assert [r["version_correlation_id"] for r in first] == [
            r["version_correlation_id"] for r in second
        ]

    def test_a_row_whose_input_carried_no_id_is_not_given_one(self):
        rows, _ = reconcile_outputs(invented(1), "a2", [{"source_guid": "G0", "content": {}}])

        assert "version_correlation_id" not in rows[0]


class TestWhenTheToolReturnsMoreRowsThanInputs:
    """``file_tool`` calls that an expansion, and ``LineageEnricher`` then re-mints
    every row and backfills ``parent_source_guid`` from the guid it replaced. A row
    that named no producer is given one there — unresolvable, and read as absent by
    every consumer, but no longer absent. Pinned so the deviation from what this
    module writes is visible here rather than only in #1044."""

    def _expanded(self):
        raw = FileUDFResult(
            [{"source_index": 0, "data": {"o": 0}}, {"source_index": None, "data": {"o": 1}}]
        )
        return reconcile_outputs(raw, "a2", records("G0"))[0]

    def test_this_module_leaves_the_invented_row_unattributed(self):
        rows = self._expanded()

        assert rows[1].get("parent_source_guid") is None

    def test_lineage_enrichment_then_gives_it_one_that_resolves_to_nothing(self):
        rows = self._expanded()
        minted = rows[1]["source_guid"]
        context = MagicMock(spec=ProcessingContext)
        context.action_name = context.agent_name = "a2"
        context.is_first_stage = False
        context.source_data = None
        context.parent_records = []
        context.record_index = 0
        context.agent_config = {}

        enriched = LineageEnricher().enrich(
            ProcessingResult(data=rows, status=ProcessingStatus.SUCCESS, is_expansion=True),
            context,
        )

        assert enriched.data[1]["parent_source_guid"] == minted
        assert resolve_source_content(enriched.data[1], None, [{"source_guid": "G0"}]) is None
