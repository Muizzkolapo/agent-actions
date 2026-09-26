"""An expansion child's correlation id is keyed on what it inherited, not on the
guid minted for it during the same pass.

``LineageEnricher`` mints a fresh ``uuid4`` ``source_guid`` for every row of a
1→N expansion and moves the identity the row arrived with to
``parent_source_guid``. ``VersionIdEnricher`` then forces a position-based
correlation id on those rows; keying it on the minted guid makes it fresh per run
and different in each branch of a versioned action, which leaves the matching
rows of two branches uncorrelated and halves a versioned aggregation.
"""

import uuid

from agent_actions.processing.enrichment import LineageEnricher, VersionIdEnricher
from agent_actions.processing.types import ProcessingContext, ProcessingResult
from agent_actions.record.envelope import RecordEnvelope
from agent_actions.utils.correlation import VersionIdGenerator
from agent_actions.utils.udf_management.registry import FileUDFResult
from agent_actions.workflow.pipeline_file_mode import reconcile_outputs

SESSION = "sess"


def config(version_base_name="a2", action_name="a2"):
    return {
        "agent_type": action_name,
        "is_versioned_agent": True,
        "version_base_name": version_base_name,
        "workflow_session_id": SESSION,
        "action_name": action_name,
    }


def parents(*guids):
    """Input records. The correlation id follows the guid, not the position: two
    records sharing an id are one entity to every consumer that keys on it, so a
    fixture that reuses ``V0`` for distinct records asserts the wrong thing."""
    return [
        {"source_guid": g, "version_correlation_id": f"V-{g}", "content": {"prev": {"id": i}}}
        for i, g in enumerate(guids)
    ]


def enrich(rows, source_mapping, agent_config, inputs, record_index=0):
    """Run the two enrichers that touch identity, in pipeline order."""
    context = ProcessingContext(
        agent_config=dict(agent_config),
        agent_name="a2",
        is_first_stage=False,
        source_data=[dict(r) for r in inputs],
    )
    context.parent_records = [dict(r) for r in inputs]
    context.record_index = record_index
    result = ProcessingResult.success(data=rows, source_guid=None, is_expansion=True)
    result.source_mapping = source_mapping
    return VersionIdEnricher().enrich(LineageEnricher().enrich(result, context), context).data


def ids(rows):
    return [row.get("version_correlation_id") for row in rows]


def file_expansion(inputs, count, agent_config=None, synthetic=False):
    """One pass of a FILE tool returning *count* rows for *inputs*.

    The registry is cleared first so an id can only repeat across passes because
    the value it hashes repeated — not because the first pass memoised it.

    With *synthetic*, the last row carries ``source_index: None`` — a row the tool
    invented, which names no input to inherit from.
    """
    VersionIdGenerator.clear()
    outputs = [{"source_index": 0, "data": {"o": i}} for i in range(count)]
    if synthetic:
        outputs[-1]["source_index"] = None
    rows, mapping = reconcile_outputs(FileUDFResult(outputs), "a2", inputs)
    return ids(enrich(rows, mapping, agent_config or config(), inputs))


def llm_expansion(parent, count, agent_config=None, record_index=0):
    """One pass of an online/batch 1→N, whose children are built by the envelope
    and so arrive carrying the parent's id verbatim rather than a derived one."""
    VersionIdGenerator.clear()
    rows = [RecordEnvelope.build("a2", {"o": i}, parent) for i in range(count)]
    return ids(enrich(rows, None, agent_config or config(), [parent], record_index))


class TestTheIdIsTheSameOnEveryRun:
    """Same inputs, same ``workflow_session_id``, twice."""

    def test_a_file_expansion_repeats_its_ids(self):
        first = file_expansion(parents("G0"), 2)
        second = file_expansion(parents("G0"), 2)

        assert first == second

    def test_an_llm_expansion_repeats_its_ids(self):
        parent = parents("G0")[0]

        assert llm_expansion(parent, 3) == llm_expansion(parent, 3)

    def test_an_expansion_of_expansion_children_repeats_its_ids(self):
        """The nested case. Every input here was itself minted a uuid4 one stage
        earlier, so the only stable thing about it is the pool identity it kept in
        ``parent_source_guid`` — which is what both mint sites take care to carry
        rather than overwrite with the intermediate guid."""
        children = [
            {
                "source_guid": str(uuid.uuid4()),
                "parent_source_guid": "G0",
                "version_correlation_id": "V0",
                "content": {"prev": {"id": 0}},
            }
        ]

        first = file_expansion([dict(r) for r in children], 2)
        second = file_expansion([dict(r) for r in children], 2)

        assert first == second

    def test_a_row_the_tool_invented_repeats_its_ids(self):
        """``source_index: None`` names no input, so ``_reattach_source_guid`` mints
        the row's guid and sets no ``parent_source_guid``; ``LineageEnricher`` then
        files that same-pass mint as the parent. Keying on the guid — the row's own
        or its fabricated parent's — leaves this row alone non-deterministic."""
        first = file_expansion(parents("G0"), 2, synthetic=True)
        second = file_expansion(parents("G0"), 2, synthetic=True)

        assert first == second


class TestTheBranchesOfAVersionedActionStillCorrelate:
    """Two branches run the same tool over the same input. Their matching rows
    must land on one id, or a fan-in over both keeps them apart and halves the
    aggregation. Keyed on a per-row minted guid they never match."""

    def test_matching_rows_of_two_branches_share_an_id(self):
        left = file_expansion(parents("G0"), 2, config(action_name="a2_v1"))
        right = file_expansion(parents("G0"), 2, config(action_name="a2_v2"))

        assert left == right

    def test_a_different_input_record_does_not_collide_with_them(self):
        """The guard on the test above: equality must come from the input being
        the same, not from every expansion collapsing onto one id."""
        left = file_expansion(parents("G0"), 2)
        other = file_expansion(parents("G9"), 2)

        assert not set(left) & set(other)


class TestUniquenessIsNotTradedAway:
    """What the minted guid was reachable for. These hold before the change too —
    they are here so a fix that buys determinism by collapsing the children
    cannot pass."""

    def test_each_child_of_one_parent_keeps_its_own_id(self):
        assert len(set(file_expansion(parents("G0"), 3))) == 3

    def test_each_child_of_an_llm_expansion_keeps_its_own_id(self):
        assert len(set(llm_expansion(parents("G0")[0], 3))) == 3

    def test_two_parents_that_share_an_ancestor_do_not_collide(self):
        """Two children of one earlier expansion share a ``parent_source_guid`` — the
        pool identity, handed on deliberately. ``record_index`` counts per record, so
        A's second child and B's first both sit at position 1: keyed on that shared
        guid they collide, and ``merge_records_by_key`` takes
        ``version_correlation_id`` as its first automatic key. The id each parent
        inherited is what separates them.
        """
        siblings = [
            {
                "source_guid": f"mint-{n}",
                "parent_source_guid": "G0",
                "version_correlation_id": f"V0#{i}",
                "content": {"prev": {"id": i}},
            }
            for i, n in enumerate("AB")
        ]

        first = llm_expansion(siblings[0], 2, record_index=0)
        second = llm_expansion(siblings[1], 2, record_index=1)

        assert len(set(first + second)) == 4

    def test_two_parents_that_carry_no_inherited_id_do_not_collide(self):
        """Upstream of the first correlated stage a record has no id to inherit, so
        the guid it was stamped with at ingestion is the only thing separating it
        from the next record — and ``record_index`` alone does not, since the
        windows overlap. This is what the fallback is for."""
        first = llm_expansion({"source_guid": "hash-1", "content": {}}, 2, record_index=0)
        second = llm_expansion({"source_guid": "hash-2", "content": {}}, 2, record_index=1)

        assert len(set(first + second)) == 4

    def test_a_later_stage_does_not_reuse_the_ids_of_the_one_above(self):
        """A chained aggregation must not hand its rows the ids the previous
        stage used, or a fan-in over both merges rows from different actions."""
        first = file_expansion(parents("G0"), 2, config(version_base_name="a2"))
        second = file_expansion(parents("G0"), 2, config(version_base_name="a3"))

        assert not set(first) & set(second)
