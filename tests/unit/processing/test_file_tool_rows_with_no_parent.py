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

import pytest

from agent_actions.processing.enrichment import LineageEnricher, VersionIdEnricher
from agent_actions.processing.source_resolution import resolve_source_content
from agent_actions.processing.types import ProcessingContext, ProcessingResult
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
    """``parent_source_guid`` is read two ways — as a fallback identity by source
    lookup, and as the row's *producer* by the gate deciding which stored rows a
    repair may replace. A synthetic row has no producer to name, and nothing is
    added for it here; what the envelope carried is left alone, because the
    FILE-mode resolver has no rule for a record's own ``source`` and skips a row
    that names nothing (#1046). Reconciling the two readers is #1022."""

    @pytest.mark.parametrize("version_merge", [False, True])
    def test_it_claims_no_producer(self, version_merge):
        rows, _ = reconcile_outputs(
            invented(2), "a2", records("G0", "G1"), version_merge=version_merge
        )

        assert [row.get("parent_source_guid") for row in rows] == [None, None]

    def test_an_ancestor_carried_from_the_input_is_left_alone(self):
        """The row takes its namespaces from ``original_data[0]``, and the envelope
        carries that record's tracking fields with them, so an input that is itself
        an expansion child hands its ancestor to a row with no producer of its own.

        Clearing it is the honest answer and breaks the run: the FILE-mode resolver
        (``scope_application._resolve_source_content``) has no rule for a record's
        own carried ``source``, so every row below is skipped ``source_unresolved``
        and the action then fails on a length mismatch. Pinned as the behaviour
        this branch deliberately leaves as it found it — see #1046 and #1022.
        """
        expansion_children = [
            {
                "source_guid": f"M{i}",
                "parent_source_guid": "POOL0",
                "content": {"a1": {"i": i}},
            }
            for i in range(2)
        ]

        rows, _ = reconcile_outputs(invented(2), "a2", expansion_children)

        assert [row.get("parent_source_guid") for row in rows] == ["POOL0", "POOL0"]

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

    def test_a_second_aggregation_does_not_collide_with_the_first(self):
        """The suffix is appended, not replaced. Replacing it would give a chained
        aggregation the same ids as the stage above, and a fan-in over both would
        merge rows from different actions — this ticket's own collapse, one stage
        later. The id grows a segment per stage, which is the price of that."""
        first, _ = reconcile_outputs(invented(2), "a2", records("G0", "G1"))
        second, _ = reconcile_outputs(invented(2), "a3", first)

        assert not (
            {r["version_correlation_id"] for r in first}
            & {r["version_correlation_id"] for r in second}
        )
        assert len(merge_records_by_key([dict(r) for r in first + second])) == 4

    def test_a_row_whose_input_carried_no_id_is_not_given_one(self):
        rows, _ = reconcile_outputs(invented(1), "a2", [{"source_guid": "G0", "content": {}}])

        assert "version_correlation_id" not in rows[0]


class TestWhenTheToolReturnsMoreRowsThanInputs:
    """``file_tool`` calls that an expansion, and ``LineageEnricher`` re-mints every
    row of one, handing the guid it replaced to ``parent_source_guid``. A row that
    named no input was already minted *here* and names no producer on purpose, so
    re-minting it there attributed it to its own previous mint — a guid no source
    pool holds (#1044). ``source_mapping`` is what the enricher reads to tell the two
    apart: the tool's own statement of which input produced a row, which the lineage
    step further down already reads the same way.
    """

    POOL = records("G0")

    def _expanded(self, outputs=None):
        """Two rows from one input: a passthrough and an invented row."""
        raw = FileUDFResult(
            outputs
            or [
                {"source_index": 0, "data": {"o": 0}},
                {"source_index": None, "data": {"o": 1}},
            ]
        )
        return reconcile_outputs(raw, "a2", self.POOL)

    def _enrich(self, rows, mapping, source_data=None):
        """Enrich as ``file_tool`` hands the result over — mapping included.

        Built through the real result rather than a mock: the mapping is the whole
        signal under test, and a mock that omitted it would exercise the path no
        production caller takes (``file_tool``/``hitl`` both set it).
        """
        result = ProcessingResult.success(data=rows, source_guid=None, is_expansion=True)
        result.source_mapping = mapping
        context = ProcessingContext(
            agent_config={"agent_type": "a2"},
            agent_name="a2",
            source_data=list(self.POOL if source_data is None else source_data),
            is_first_stage=False,
        )
        return LineageEnricher().enrich(result, context).data

    def test_this_module_leaves_the_invented_row_unattributed(self):
        rows, _ = self._expanded()

        assert rows[1].get("parent_source_guid") is None

    def test_the_invented_row_keeps_the_identity_it_was_minted(self):
        """Nothing is gained by minting twice: the first mint is already unique, so
        the second only costs the row the identity anything upstream recorded."""
        rows, mapping = self._expanded()
        minted = rows[1]["source_guid"]

        assert self._enrich(rows, mapping)[1]["source_guid"] == minted

    def test_the_invented_row_still_claims_no_producer(self):
        rows, mapping = self._expanded()

        assert self._enrich(rows, mapping)[1].get("parent_source_guid") is None

    def test_no_row_ends_up_claiming_a_producer_the_pool_cannot_resolve(self):
        """The defect as the invariant it breaks. ``parent_source_guid`` is a
        source-pool identity (``record/envelope.py``), so one that resolves nowhere
        asserts a lineage edge to an entity that never existed — and every consumer
        reads it as absent, which is what kept it quiet.
        """
        rows, mapping = self._expanded()
        pool = {r["source_guid"] for r in self.POOL}

        claimed = {
            row["parent_source_guid"]
            for row in self._enrich(rows, mapping)
            if row.get("parent_source_guid")
        }

        assert claimed <= pool, f"claims no pool record holds: {sorted(claimed - pool)}"

    def test_the_row_that_named_an_input_is_still_re_minted_and_attributed(self):
        """Guard on the guard: every assertion above also passes if the expansion
        re-mint stopped happening at all, and it is what keeps two children of one
        input off a single identity."""
        enriched = self._enrich(*self._expanded())

        assert enriched[0]["source_guid"] != "G0"
        assert enriched[0]["parent_source_guid"] == "G0"

    def test_the_invented_row_is_still_given_its_own_target_id(self):
        """The rest of the block still runs for it. target_id is per-stage, so every
        row arrives without one and two rows sharing one collide downstream."""
        enriched = self._enrich(*self._expanded())

        assert enriched[1]["target_id"]
        assert enriched[1]["target_id"] != enriched[0]["target_id"]

    def test_an_ancestor_the_row_already_carried_is_still_left_alone(self):
        """Nested expansion: the attribution the outer mint wrote is the
        pool-resolvable one, and must not be replaced by the intermediate guid."""
        rows, mapping = self._expanded()
        rows[1]["parent_source_guid"] = "G0"

        assert self._enrich(rows, mapping)[1]["parent_source_guid"] == "G0"

    def test_an_invented_row_arriving_with_no_identity_is_still_given_one(self):
        """Not minting at all would hand ``RequiredFieldsEnricher`` a nameless row
        and fail the action, where today it is merely minted unattributed."""
        enriched = self._enrich([{"content": {"a2": {"o": 0}}}], {0: None}, source_data=[])

        assert enriched[0]["source_guid"]
        assert enriched[0].get("parent_source_guid") is None
