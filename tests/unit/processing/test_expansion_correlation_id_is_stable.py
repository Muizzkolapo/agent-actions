"""An expansion child's correlation id is keyed on what it inherited, not on what
was minted for it during the same pass.

``LineageEnricher`` gives every row of a 1→N expansion a fresh ``uuid4``
``source_guid`` so the rows cannot collide in a store keyed by identity, and moves
the identity the row arrived with to ``parent_source_guid``. ``VersionIdEnricher``
then runs and forces a position-based correlation id on the same rows. Keying that
id on the row's ``source_guid`` reads the uuid4 minted moments earlier, so the id
is fresh per run — which is the one thing
``VersionIdGenerator.add_version_correlation_id`` raises over a missing
``workflow_session_id`` to protect.

The inherited identity is the stable key: equal across runs, and equal across the
branches of a versioned action, which is what lets the matching rows of two
branches correlate instead of silently halving a versioned aggregation.
``record_index`` keeps the children of one parent apart, so nothing about
uniqueness rests on the guid.
"""

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
    return [
        {"source_guid": g, "version_correlation_id": f"V{i}", "content": {"prev": {"id": i}}}
        for i, g in enumerate(guids)
    ]


def enrich(rows, source_mapping, agent_config, inputs):
    """Run the two enrichers that touch identity, in pipeline order."""
    context = ProcessingContext(
        agent_config=dict(agent_config),
        agent_name="a2",
        is_first_stage=False,
        source_data=[dict(r) for r in inputs],
    )
    context.parent_records = [dict(r) for r in inputs]
    context.record_index = 0
    result = ProcessingResult.success(data=rows, source_guid=None, is_expansion=True)
    result.source_mapping = source_mapping
    return VersionIdEnricher().enrich(LineageEnricher().enrich(result, context), context).data


def ids(rows):
    return [row.get("version_correlation_id") for row in rows]


def file_expansion(inputs, count, agent_config=None):
    """One pass of a FILE tool returning *count* rows for *inputs*.

    The registry is cleared first so an id can only repeat across passes because
    the value it hashes repeated — not because the first pass memoised it.
    """
    VersionIdGenerator.clear()
    raw = FileUDFResult([{"source_index": 0, "data": {"o": i}} for i in range(count)])
    rows, mapping = reconcile_outputs(raw, "a2", inputs)
    return ids(enrich(rows, mapping, agent_config or config(), inputs))


def llm_expansion(parent, count, agent_config=None):
    """One pass of an online/batch 1→N, whose children are built by the envelope
    and so arrive carrying the parent's id verbatim rather than a derived one."""
    VersionIdGenerator.clear()
    rows = [RecordEnvelope.build("a2", {"o": i}, parent) for i in range(count)]
    return ids(enrich(rows, None, agent_config or config(), [parent]))


class TestTheIdIsTheSameOnEveryRun:
    """Same inputs, same ``workflow_session_id``, twice."""

    def test_a_file_expansion_repeats_its_ids(self):
        first = file_expansion(parents("G0"), 2)
        second = file_expansion(parents("G0"), 2)

        assert first == second

    def test_an_llm_expansion_repeats_its_ids(self):
        parent = parents("G0")[0]

        assert llm_expansion(parent, 3) == llm_expansion(parent, 3)

    def test_an_expansion_of_records_that_carry_no_identity_repeats_its_ids(self):
        """A first-stage row inherits nothing, so there is no parent guid to key
        on. The fallback has to be a constant rather than the minted guid —
        ``record_index`` is already carrying uniqueness."""
        first_stage = [{"content": {"prev": {"id": 0}}}]

        first = file_expansion([dict(r) for r in first_stage], 2)
        second = file_expansion([dict(r) for r in first_stage], 2)

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

    def test_a_later_stage_does_not_reuse_the_ids_of_the_one_above(self):
        """A chained aggregation must not hand its rows the ids the previous
        stage used, or a fan-in over both merges rows from different actions."""
        first = file_expansion(parents("G0"), 2, config(version_base_name="a2"))
        second = file_expansion(parents("G0"), 2, config(version_base_name="a3"))

        assert not set(first) & set(second)
